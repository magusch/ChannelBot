# Create a new file: unit_tests/test_crud.py

import pytest
from unittest.mock import MagicMock
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import davai_s_nami_bot.database.database_orm as db_orm
import davai_s_nami_bot.crud as crud_module
from davai_s_nami_bot.crud import get_ready_to_post_events
from davai_s_nami_bot.database.models import Events2Posts, EventsNotApproved, Place, Category
from davai_s_nami_bot.events import Event
from davai_s_nami_bot.pydantic_models import EventRequestParameters

@pytest.fixture
def mock_db_session(monkeypatch):
    mock_session = MagicMock()
    @contextmanager
    def fake_get_db_session():
        yield mock_session

    monkeypatch.setattr(db_orm, 'get_db_session', fake_get_db_session)
    return mock_session

def test_get_ready_to_post_events(mock_db_session, monkeypatch):
    # 1) Настраиваем возвращаемые модели из запроса
    mock_model_instance = MagicMock(spec=Events2Posts)
    mock_db_session.query.return_value.filter.return_value.all.return_value = [mock_model_instance]

    # Arrange: Set up the mock return value
    mock_event_data = {
        'id': 1, 'title': 'Test Event', 'status': 'ReadyToPost',
        'post': 'post', 'full_text': 'f',
        'url': 'url', 'from_date': '2025-07-01', 'to_date': '2025-07-10',
        'image': 'image', 'event_id': 'EVENT_333', 'price': '300₽', 'price_int': 400, 'category': 'Леукция', 'address': 'address',
        'ticket_url': 'ticket_url', 'source': 'Other'

    }
    expected_event = Event(**mock_event_data)

    monkeypatch.setattr(crud_module.Event, 'from_database', lambda data: expected_event)

    # Act: Call the function
    result = crud_module.get_ready_to_post_events()

    # Assert: Check if the result is as expected
    assert len(result) == 1
    assert result[0].title == 'Test Event'
    assert result[0].status == 'ReadyToPost'


# --- route_events_to_api ---------------------------------------------------

MSK = timezone(timedelta(hours=3))


def _e2p(idx, *, status='ReadyToPost', is_ready=None, score=50,
         main_category_id=1, days_ahead=2):
    """Минимальный билдер Events2Posts для тестов route_events_to_api."""
    base = datetime.now(MSK) + timedelta(days=days_ahead)
    return Events2Posts(
        title=f'evt-{idx}',
        event_id=f'EVT-{idx}',
        status=status,
        is_ready=is_ready,
        score=score,
        main_category_id=main_category_id,
        from_date=base,
        to_date=base + timedelta(hours=2),
        source='test',
        url='', post='', full_text='', ticket_url='',
    )


def _seed_channel_queue(db, n: int, days_ahead: int = 3):
    """Готовая к каналу очередь (ReadyToPost & is_ready=True) — для прохождения safety floor."""
    for i in range(n):
        db.add(_e2p(f'queue-{i}', is_ready=True, score=80, days_ahead=days_ahead))
    db.commit()


def test_route_events_to_api_respects_safety_floor(db_session_fixture):
    db = db_session_fixture
    # Очередь короче min_channel_queue=5
    _seed_channel_queue(db, n=3)
    # И есть событие, которое по критериям могло бы уйти
    db.add(_e2p('candidate', score=10))
    db.commit()

    routed = crud_module.route_events_to_api(min_channel_queue=5)
    assert routed == []
    # Кандидат остался в ReadyToPost
    cand = db.query(Events2Posts).filter_by(event_id='EVT-candidate').one()
    assert cand.status == 'ReadyToPost'


def test_route_events_to_api_selects_by_each_criterion(db_session_fixture):
    db = db_session_fixture
    _seed_channel_queue(db, n=20)
    # 1) hard_min_score
    db.add(_e2p('trash', score=20, main_category_id=1, days_ahead=3))
    # 2) low score + low_category
    db.add(_e2p('low-cat', score=50, main_category_id=14, days_ahead=3))
    # 3) far date
    db.add(_e2p('far', score=90, main_category_id=1, days_ahead=30))
    # Контрольные — не должны уходить
    db.add(_e2p('keep-high', score=80, main_category_id=1, days_ahead=3))
    db.add(_e2p('keep-low-but-good-cat', score=50, main_category_id=1, days_ahead=3))
    db.commit()

    routed_ids = crud_module.route_events_to_api(
        min_score=55, hard_min_score=35,
        low_category_ids=[2, 14], far_days=14, min_channel_queue=5,
    )

    def status_of(eid):
        return db.query(Events2Posts).filter_by(event_id=eid).one().status

    assert status_of('EVT-trash') == 'OnlyApi'
    assert status_of('EVT-low-cat') == 'OnlyApi'
    assert status_of('EVT-far') == 'OnlyApi'
    assert status_of('EVT-keep-high') == 'ReadyToPost'
    assert status_of('EVT-keep-low-but-good-cat') == 'ReadyToPost'
    assert len(routed_ids) == 3


def test_route_events_to_api_skips_is_ready_and_past(db_session_fixture):
    db = db_session_fixture
    _seed_channel_queue(db, n=20)
    # is_ready=True — AI уже вложился, не выкидываем
    db.add(_e2p('ai-prepped', is_ready=True, score=10, days_ahead=3))
    # from_date в прошлом — `update_expired_events` сам разрулит
    db.add(_e2p('past', is_ready=None, score=10, days_ahead=-1))
    db.commit()

    crud_module.route_events_to_api(min_channel_queue=5)

    assert db.query(Events2Posts).filter_by(event_id='EVT-ai-prepped').one().status == 'ReadyToPost'
    assert db.query(Events2Posts).filter_by(event_id='EVT-past').one().status == 'ReadyToPost'


def test_get_events_by_date_and_category_includes_only_api(db_session_fixture):
    db = db_session_fixture
    now = datetime.now(MSK)
    db.add(Events2Posts(
        title='only-api-evt', event_id='OA-1', status='OnlyApi', is_ready=None,
        from_date=now + timedelta(days=2), to_date=now + timedelta(days=2, hours=2),
        source='test', url='', post='', full_text='', ticket_url='',
    ))
    db.commit()

    params = EventRequestParameters(
        date_from=now - timedelta(days=1),
        date_to=now + timedelta(days=10),
        status='active',  # любой не-'all' значение → срабатывает фильтр
        limit=50,
    )
    result = crud_module.get_events_by_date_and_category(params)
    titles = [e['title'] for e in result['events']]
    assert 'only-api-evt' in titles


# --- find_exhibition_duplicate --------------------------------------------


def _exhibition(idx, *, title, place_id, status='Posted', main_category_id=11,
                explored_days_ago=10):
    explored = datetime.now(timezone.utc) - timedelta(days=explored_days_ago)
    base = datetime.now(MSK) + timedelta(days=5)
    return Events2Posts(
        title=title,
        event_id=f'EX-{idx}',
        status=status,
        main_category_id=main_category_id,
        place_id=place_id,
        from_date=base,
        to_date=base + timedelta(hours=2),
        explored_date=explored,
        source='timepad',
        url='', post='', full_text='', ticket_url='',
    )


def test_find_exhibition_duplicate_detects_same_place_similar_title(db_session_fixture):
    db = db_session_fixture
    # Realistic Timepad re-issue: identical title at the same place, different from_date.
    db.add(_exhibition(1, title='Выставка Кустодиева в Михайловском саду', place_id=42))
    db.commit()

    dup = crud_module.find_exhibition_duplicate(
        title='Выставка Кустодиева в Михайловском саду',
        place_id=42, main_category_id=11,
    )
    assert dup != 0


def test_find_exhibition_duplicate_ignores_different_place(db_session_fixture):
    db = db_session_fixture
    db.add(_exhibition(1, title='Выставка Кустодиева в Михайловском саду', place_id=42))
    db.commit()

    dup = crud_module.find_exhibition_duplicate(
        title='Выставка Кустодиева в Михайловском саду',
        place_id=99, main_category_id=11,
    )
    assert dup == 0


def test_find_exhibition_duplicate_ignores_non_exhibitions(db_session_fixture):
    db = db_session_fixture
    db.add(_exhibition(1, title='Концерт группы X', place_id=42, main_category_id=1))
    db.commit()

    # Even with category-id mismatch in fixture, the helper short-circuits on caller's id.
    dup = crud_module.find_exhibition_duplicate(
        title='Концерт группы X', place_id=42, main_category_id=1,
    )
    assert dup == 0


def test_find_exhibition_duplicate_respects_lookup_window(db_session_fixture):
    db = db_session_fixture
    db.add(_exhibition(1, title='Old Show', place_id=42, explored_days_ago=400))
    db.commit()

    dup = crud_module.find_exhibition_duplicate(
        title='Old Show', place_id=42, main_category_id=11, lookup_days=180,
    )
    assert dup == 0


def test_find_exhibition_duplicate_ignores_rejected_status(db_session_fixture):
    db = db_session_fixture
    db.add(_exhibition(1, title='Rejected Show', place_id=42, status='Rejected'))
    db.add(_exhibition(2, title='Expired Show', place_id=42, status='Expired'))
    db.commit()

    assert crud_module.find_exhibition_duplicate(
        title='Rejected Show', place_id=42, main_category_id=11,
    ) == 0
    assert crud_module.find_exhibition_duplicate(
        title='Expired Show', place_id=42, main_category_id=11,
    ) == 0


def test_find_exhibition_duplicate_sees_through_emoji_and_boilerplate(db_session_fixture):
    """The stored title carries an AI-added emoji, the incoming one — Timepad's
    "Входной билет на ..." wrapper. Both must still match the same core."""
    db = db_session_fixture
    db.add(_exhibition(1, title='💭 Выставка «Так не бывает»', place_id=42))
    db.commit()

    dup = crud_module.find_exhibition_duplicate(
        title='Входной билет на выставку «Так не бывает»',
        place_id=42, main_category_id=11,
    )
    assert dup != 0


# --- embedding dedup helpers ----------------------------------------------


def test_dates_overlap():
    d = lambda day: datetime(2026, 7, day)
    # Intersecting ranges
    assert crud_module._dates_overlap(d(1), d(10), d(5), d(15)) is True
    # Touching boundaries count as overlap
    assert crud_module._dates_overlap(d(1), d(5), d(5), d(9)) is True
    # Disjoint ranges
    assert crud_module._dates_overlap(d(1), d(4), d(5), d(9)) is False
    # Missing to_date falls back to from_date
    assert crud_module._dates_overlap(d(3), None, d(1), d(5)) is True
    assert crud_module._dates_overlap(d(7), None, d(1), d(5)) is False
    # Missing from_date → no overlap claim
    assert crud_module._dates_overlap(None, None, d(1), d(5)) is False


def test_enrich_event_from_duplicate_fills_only_empty_fields(db_session_fixture):
    db = db_session_fixture
    survivor = _exhibition(1, title='Выставка Тело', place_id=42)
    survivor.image = ''
    survivor.price = '500₽'  # already set — must not be overwritten
    db.add(survivor)
    db.commit()

    updated = crud_module._enrich_event_from_duplicate(
        db,
        survivor.id,
        {'image': 'https://img.example/1.jpg', 'price': '300₽', 'ticket_url': 'https://t.example'},
    )

    assert 'image' in updated and 'ticket_url' in updated
    assert 'price' not in updated
    assert survivor.image == 'https://img.example/1.jpg'
    assert survivor.price == '500₽'


# --- Place category override --------------------------------------------------

def _place(db, place_id, *, name='Standup Club', category=None):
    db.add(Place(
        id=place_id, place_name=name, place_address='addr', place_url='url',
        place_metro='metro', place_image='img', category=category,
    ))


def test_load_place_category_overrides_resolves_id_and_skips_empty(db_session_fixture):
    db = db_session_fixture
    db.add(Category(id=10, name='Стэндап'))
    _place(db, 1, category='Стэндап')        # resolvable to id 10
    _place(db, 2, category='  ')             # whitespace only -> skipped
    _place(db, 3, category=None)             # null -> skipped
    _place(db, 4, category='Несуществующая')  # no Category row -> id None
    db.commit()

    overrides = crud_module._load_place_category_overrides(db)

    assert overrides == {
        1: ('Стэндап', 10),
        4: ('Несуществующая', None),
    }


def test_apply_place_category_override_sets_category_and_main_id():
    event_dict = {'place_id': 1, 'category': 'Концерты'}
    crud_module._apply_place_category_override(event_dict, {1: ('Стэндап', 10)})
    assert event_dict['category'] == 'Стэндап'
    assert event_dict['main_category_id'] == 10


def test_apply_place_category_override_without_known_id_keeps_main_id_unset():
    event_dict = {'place_id': 4, 'category': 'Концерты'}
    crud_module._apply_place_category_override(event_dict, {4: ('Несуществующая', None)})
    assert event_dict['category'] == 'Несуществующая'
    assert 'main_category_id' not in event_dict


def test_apply_place_category_override_noop_without_match():
    no_place = {'category': 'Концерты'}
    crud_module._apply_place_category_override(no_place, {1: ('Стэндап', 10)})
    assert no_place == {'category': 'Концерты'}

    unlisted = {'place_id': 99, 'category': 'Концерты'}
    crud_module._apply_place_category_override(unlisted, {1: ('Стэндап', 10)})
    assert unlisted == {'place_id': 99, 'category': 'Концерты'}


def test_create_event_drops_main_category_id_for_not_approved(db_session_fixture):
    db = db_session_fixture
    # main_category_id has no column on EventsNotApproved — must be dropped, not crash.
    result = crud_module.create_event(
        db,
        {
            'event_id': 'e1', 'title': 'Стендап вечер', 'url': 'u', 'ticket_url': 't',
            'source': 'timepad', 'category': 'Стэндап', 'main_category_id': 10,
        },
        EventsNotApproved,
    )
    row = db.query(EventsNotApproved).get(result['id'])
    assert row.category == 'Стэндап'
    assert not hasattr(EventsNotApproved, 'main_category_id')


# --- get_place_reputation -----------------------------------------------------

def _rep_e2p(idx, *, place_id, status):
    base = datetime.now(MSK) + timedelta(days=3)
    return Events2Posts(
        title=f'r-{idx}', event_id=f'R-{idx}', status=status, place_id=place_id,
        from_date=base, to_date=base + timedelta(hours=2), source='timepad',
        url='', post='', full_text='', ticket_url='',
    )


def _rep_na(idx, *, place_id, status, score):
    base = datetime.now(MSK) + timedelta(days=3)
    return EventsNotApproved(
        title=f'n-{idx}', event_id=f'N-{idx}', status=status, place_id=place_id,
        score=score, from_date=base, to_date=base + timedelta(hours=2),
        source='timepad', url='', full_text='', ticket_url='',
    )


def test_get_place_reputation_aggregates_statuses(db_session_fixture):
    db = db_session_fixture
    db.add_all([
        _rep_e2p(1, place_id=7, status='Posted'),
        _rep_e2p(2, place_id=7, status='Posted'),
        _rep_e2p(3, place_id=7, status='ReadyToPost'),
        _rep_e2p(4, place_id=7, status='OnlyApi'),
        _rep_e2p(5, place_id=7, status='Rejected'),
        _rep_e2p(6, place_id=7, status='Expired'),  # neutral, ignored
    ])
    db.commit()

    rep = crud_module.get_place_reputation()
    assert rep[7] == {"posted": 2, "ready": 1, "onlyapi": 1, "rejected": 1, "spam": 0}


def test_get_place_reputation_excludes_auto_rejected(db_session_fixture):
    db = db_session_fixture
    db.add_all([
        # auto-rejected (low score) — must NOT count
        _rep_na(1, place_id=9, status='rejected', score=20),
        # informed rejection (high score) — counts
        _rep_na(2, place_id=9, status='rejected', score=60),
        # spam counts regardless of score
        _rep_na(3, place_id=9, status='spam', score=10),
        # duplicate never counts
        _rep_na(4, place_id=9, status='duplicate', score=90),
    ])
    db.commit()

    rep = crud_module.get_place_reputation(auto_reject_threshold=39)
    assert rep[9]["rejected"] == 1
    assert rep[9]["spam"] == 1