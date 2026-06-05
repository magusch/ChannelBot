import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from davai_s_nami_bot.helper.post_helper import PostHelper, PlaceView, DictAsMethods
from davai_s_nami_bot.database.models import (
    Events2Posts, EventsNotApproved, Place, PlaceKeyword, PlaceSchedule, Base,
)
from davai_s_nami_bot import crud


# ─── Fixtures ───────────────────────────────────────────────────────

def _make_event_dict(**overrides):
    """Minimal event dict for PostHelper."""
    base = {
        "id": 1,
        "title": "Концерт группы Кино",
        "full_text": "Легендарная группа Кино даёт концерт в клубе А2.",
        "prepared_text": None,
        "from_date": datetime(2026, 5, 15, 19, 0, tzinfo=timezone(timedelta(hours=3))),
        "to_date": datetime(2026, 5, 15, 22, 0, tzinfo=timezone(timedelta(hours=3))),
        "address": "пр. Медиков 3",
        "price": "500 руб",
        "url": "https://example.com/event/1",
        "ticket_url": "https://tickets.example.com/1",
        "category": "Концерты",
        "source": "timepad",
    }
    base.update(overrides)
    return base


def _make_place(db, name="A2 Green Concert", address="пр. Медиков 3",
                url="https://a2.ru", metro="Петроградская"):
    place = Place(
        place_name=name,
        place_address=address,
        place_url=url,
        place_metro=metro,
        place_image="",
    )
    db.add(place)
    db.flush()
    return place


def _make_place_keyword(db, place, keyword):
    kw = PlaceKeyword(place_id=place.id, place_keyword=keyword)
    db.add(kw)
    db.flush()
    return kw


def _make_not_approved_event(db, **overrides):
    data = {
        "event_id": "timepad-123",
        "title": "Test Event",
        "full_text": "Some text about event.",
        "post": "Ready post text",
        "url": "https://example.com",
        "ticket_url": "https://tickets.example.com",
        "price": "Бесплатно",
        "address": "ул. Рубинштейна 13",
        "from_date": datetime(2026, 6, 1, 18, 0),
        "to_date": datetime(2026, 6, 1, 22, 0),
        "category": "Концерты",
        "source": "timepad",
        "status": "approved",
    }
    data.update(overrides)
    event = EventsNotApproved(**data)
    db.add(event)
    db.flush()
    return event


# ─── DictAsMethods ──────────────────────────────────────────────────────

class TestDictAsMethods:
    def test_getattr(self):
        d = DictAsMethods({"title": "Hello", "price": "100"})
        assert d.title == "Hello"
        assert d.price == "100"

    def test_setattr(self):
        d = DictAsMethods({"title": "Hello"})
        d.title = "World"
        assert d.title == "World"
        assert d.data["title"] == "World"

    def test_missing_attr_raises(self):
        d = DictAsMethods({"title": "Hello"})
        with pytest.raises(AttributeError):
            _ = d.nonexistent


# ─── PostHelper unit tests (no DB) ─────────────────────────────────

class TestPostHelperUnit:
    def test_price_int_free(self):
        assert PostHelper.price_int("Бесплатно") == 0
        assert PostHelper.price_int("бесплатный вход") == 0

    def test_price_int_single(self):
        assert PostHelper.price_int("500 руб") == 500

    def test_price_int_range(self):
        # "от 300 до 1500" → min of [300, 1500]
        assert PostHelper.price_int("от 300 до 1500 руб") == 300

    def test_price_int_empty(self):
        assert PostHelper.price_int("") == -1
        assert PostHelper.price_int(None) == -1

    def test_post_markdown_basic(self):
        event = _make_event_dict()
        helper = PostHelper(event)
        post = helper.post_markdown()

        assert "15 мая" in post
        assert "онцерт" in post  # title escaping: К*онцерт...*
        assert "19:00" in post
        assert "22:00" in post
        assert "500" in post

    def test_post_markdown_uses_prepared_text_over_full_text(self):
        event = _make_event_dict(prepared_text="Подготовленный текст")
        helper = PostHelper(event)
        post = helper.post_markdown()

        assert "Подготовленный" in post
        assert "Легендарная" not in post

    def test_post_markdown_uses_full_text_when_no_prepared(self):
        event = _make_event_dict(prepared_text=None)
        helper = PostHelper(event)
        post = helper.post_markdown()

        assert "Легендарная" in post

    def test_post_markdown_prefers_ticket_url(self):
        event = _make_event_dict(
            ticket_url="https://tickets.example.com/1",
            url="https://example.com/event/1",
        )
        helper = PostHelper(event)
        post = helper.post_markdown()

        assert "tickets.example.com" in post

    def test_post_markdown_falls_back_to_url(self):
        event = _make_event_dict(ticket_url=None)
        # ticket_url missing → PostHelper falls back to url
        del event["ticket_url"]
        helper = PostHelper(event)
        post = helper.post_markdown()

        assert "example.com/event/1" in post

    def test_address_markdown_no_place(self):
        event = _make_event_dict()
        helper = PostHelper(event, place=None)
        addr = helper.address_markdown()

        # Must contain the escaped address
        assert "Медиков" in addr

    def test_address_markdown_with_place(self):
        place_view = PlaceView(
            id=1,
            name="A2 Green Concert",
            address="пр. Медиков 3",
            url="https://a2.ru",
            metro="Петроградская",
        )

        event = _make_event_dict()
        helper = PostHelper(event, place=place_view)
        addr = helper.address_markdown()

        assert "A2" in addr
        assert "Медиков" in addr
        assert "Петроградская" in addr

    def test_address_markdown_place_without_metro(self):
        place_view = PlaceView(
            id=2,
            name="Small Venue",
            address="ул. Ленина 1",
            url="",
            metro="",
        )
        event = _make_event_dict()
        helper = PostHelper(event, place=place_view)
        addr = helper.address_markdown()

        assert "Small Venue" in addr
        assert "Ленина" in addr

    def test_main_category_concert(self):
        event = _make_event_dict(category="Концерты")
        helper = PostHelper(event)
        cat_id = helper.main_category()

        assert cat_id == 1  # Концерты = 1

    def test_main_category_none(self):
        event = _make_event_dict(category=None)
        helper = PostHelper(event)
        assert helper.main_category() is None

    def test_date_to_title_same_day(self):
        event = _make_event_dict(
            from_date=datetime(2026, 5, 15, 19, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 15, 22, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper.date_to_title() == "15 мая"

    def test_date_to_title_range(self):
        event = _make_event_dict(
            from_date=datetime(2026, 5, 10, 19, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 15, 22, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper.date_to_title() == "10 – 15 мая"

    def test_date_to_title_two_consecutive_days(self):
        event = _make_event_dict(
            from_date=datetime(2026, 5, 10, 19, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 11, 22, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper.date_to_title() == "10 и 11 мая"

    def test_date_to_title_cross_month(self):
        event = _make_event_dict(
            from_date=datetime(2026, 5, 28, 19, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 6, 3, 22, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper.date_to_title() == "28 мая – 3 июня"

    def test_reduce_text_short(self):
        event = _make_event_dict()
        helper = PostHelper(event)
        short_text = "Короткий текст."
        assert helper.reduce_text(short_text) == short_text

    def test_reduce_text_long(self):
        event = _make_event_dict()
        helper = PostHelper(event)
        long_text = "А. " * 200  # ~600 chars
        result = helper.reduce_text(long_text)
        assert len(result) < 550


# ─── Exhibition logic ───────────────────────────────────────────────

class TestExhibition:
    def test_is_long_exhibition_true(self):
        event = _make_event_dict(
            main_category_id=11,
            from_date=datetime(2026, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 20, 18, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper._is_long_exhibition() is True

    def test_is_long_exhibition_false_short(self):
        event = _make_event_dict(
            main_category_id=11,
            from_date=datetime(2026, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 5, 18, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper._is_long_exhibition() is False

    def test_is_long_exhibition_false_wrong_category(self):
        event = _make_event_dict(
            main_category_id=1,
            from_date=datetime(2026, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 20, 18, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper._is_long_exhibition() is False

    def test_long_exhibition_title(self):
        event = _make_event_dict(
            main_category_id=11,
            from_date=datetime(2026, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 20, 18, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event)
        assert helper.date_to_title() == "До 20 мая"

    def test_long_exhibition_schedule_from_place(self):
        place_view = PlaceView(
            id=1,
            name="Gallery",
            address="ул. Галерейная 1",
            schedule_str="Вт-Вск 11:00-20:00",
        )

        event = _make_event_dict(
            main_category_id=11,
            from_date=datetime(2026, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 20, 18, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event, place=place_view)
        assert helper.date_to_post() == "Вт-Вск 11:00-20:00"

    def test_long_exhibition_schedule_fallback(self):
        event = _make_event_dict(
            main_category_id=11,
            from_date=datetime(2026, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=3))),
            to_date=datetime(2026, 5, 20, 18, 0, tzinfo=timezone(timedelta(hours=3))),
        )
        helper = PostHelper(event, place=None)
        schedule = helper.date_to_post()
        # Fallback: derived from event time range
        assert "10:00" in schedule
        assert "18:00" in schedule


# ─── DB integration tests ──────────────────────────────────────────

class TestResolvePlace:
    def test_resolve_by_place_id(self, db_session_fixture):
        db = db_session_fixture
        place = _make_place(db)

        event_data = _make_event_dict(place_id=place.id)
        resolved = crud._resolve_place(db, event_data)

        assert resolved is not None
        assert resolved.id == place.id

    def test_resolve_by_address_keyword(self, db_session_fixture):
        db = db_session_fixture
        place = _make_place(db, name="A2 Green Concert", address="пр. Медиков 3")
        _make_place_keyword(db, place, "Медиков")
        db.commit()

        event_data = _make_event_dict(place_id=None, address="пр. Медиков 3")
        resolved = crud._resolve_place(db, event_data)

        assert resolved is not None
        assert resolved.id == place.id

    def test_resolve_none_when_no_match(self, db_session_fixture):
        db = db_session_fixture
        event_data = _make_event_dict(place_id=None, address="Неизвестная улица 99")
        resolved = crud._resolve_place(db, event_data)

        assert resolved is None


class TestMoveApprovedToPosts:
    def test_move_single_event(self, db_session_fixture):
        db = db_session_fixture
        event = _make_not_approved_event(db)
        db.commit()

        moved_ids = crud.move_approved_to_posts()

        assert len(moved_ids) == 1
        # Verify it was inserted into Events2Posts
        new_event = db.query(Events2Posts).filter_by(id=moved_ids[0]).first()
        assert new_event is not None
        assert new_event.status == "ReadyToPost"
        assert new_event.prepared_text == "Ready post text"
        assert new_event.queue is not None

        # Verify it was removed from NotApproved
        remaining = db.query(EventsNotApproved).filter_by(event_id="timepad-123").first()
        assert remaining is None

    def test_skip_non_approved(self, db_session_fixture):
        db = db_session_fixture
        _make_not_approved_event(db, status="new", event_id="new-1")
        _make_not_approved_event(db, status="rejected", event_id="rej-1")
        _make_not_approved_event(db, status="approved", event_id="app-1")
        db.commit()

        moved_ids = crud.move_approved_to_posts()

        assert len(moved_ids) == 1
        # 'new' and 'rejected' remain untouched
        assert db.query(EventsNotApproved).filter_by(event_id="new-1").first() is not None
        assert db.query(EventsNotApproved).filter_by(event_id="rej-1").first() is not None

    def test_duplicate_event_id_deletes_from_not_approved(self, db_session_fixture):
        db = db_session_fixture
        # Already exists in Events2Posts
        existing = Events2Posts(
            event_id="timepad-123", title="Existing", url="http://x",
            ticket_url="", status="Posted", source="timepad",
        )
        db.add(existing)
        db.flush()

        # And a NotApproved row with the same event_id
        _make_not_approved_event(db, event_id="timepad-123")
        db.commit()

        moved_ids = crud.move_approved_to_posts()

        assert len(moved_ids) == 0
        # Should be removed from NotApproved
        remaining = db.query(EventsNotApproved).filter_by(event_id="timepad-123").count()
        assert remaining == 0

    def test_move_resolves_place(self, db_session_fixture):
        db = db_session_fixture
        place = _make_place(db, name="Рубинштейна 13", address="ул. Рубинштейна 13")
        _make_place_keyword(db, place, "Рубинштейна")
        _make_not_approved_event(db, address="ул. Рубинштейна 13")
        db.commit()

        moved_ids = crud.move_approved_to_posts()
        new_event = db.query(Events2Posts).filter_by(id=moved_ids[0]).first()
        assert new_event.place_id == place.id

    def test_move_sets_main_category(self, db_session_fixture):
        db = db_session_fixture
        _make_not_approved_event(db, category="Концерты")
        db.commit()

        moved_ids = crud.move_approved_to_posts()
        new_event = db.query(Events2Posts).filter_by(id=moved_ids[0]).first()
        assert new_event.main_category_id == 1

    def test_move_sets_price_int(self, db_session_fixture):
        db = db_session_fixture
        _make_not_approved_event(db, price="500 руб")
        db.commit()

        moved_ids = crud.move_approved_to_posts()
        new_event = db.query(Events2Posts).filter_by(id=moved_ids[0]).first()
        assert new_event.price_int == 500


class TestRemakeEventPost:
    def test_remake_preview(self, db_session_fixture):
        db = db_session_fixture
        event = Events2Posts(
            event_id="test-1", title="Test Event", full_text="Some text.",
            post="Old post", prepared_text="Prepared text.",
            url="https://example.com", ticket_url="https://tickets.example.com",
            status="ReadyToPost", price="300 руб", address="Невский 1",
            from_date=datetime(2026, 6, 1, 19, 0),
            to_date=datetime(2026, 6, 1, 22, 0),
            category="Лекции", source="timepad",
        )
        db.add(event)
        db.commit()

        result = crud.remake_event_post(event_id=event.id, save=False)

        assert result is not None
        assert result["saved"] is False
        assert "Test Event" in result["post"] or "Test" in result["post"]
        assert result["price_int"] == 300
        # Not saved in preview mode
        db.refresh(event)
        assert event.post == "Old post"

    def test_remake_save(self, db_session_fixture):
        db = db_session_fixture
        event = Events2Posts(
            event_id="test-2", title="Save Test", full_text="Text.",
            post="Old post", prepared_text="Prepared.",
            url="https://example.com", ticket_url="",
            status="ReadyToPost", price="Бесплатно", address="Адрес",
            from_date=datetime(2026, 6, 1, 19, 0),
            to_date=datetime(2026, 6, 1, 22, 0),
            category="Стэндап", source="timepad",
        )
        db.add(event)
        db.commit()

        result = crud.remake_event_post(event_id=event.id, save=True)

        assert result["saved"] is True
        assert result["price_int"] == 0  # Бесплатно = free
        # No pre-seeded SubCategory("Стэндап") — resolver creates new SubCategory
        # under auto-created Category("Other"), which gets id=1 in a fresh test DB
        assert result["main_category_id"] == 1
        # Saved to DB
        db.refresh(event)
        assert event.post != "Old post"
        assert event.main_category_id == 1

    def test_remake_not_found(self, db_session_fixture):
        result = crud.remake_event_post(event_id=99999, save=False)
        assert result is None


class TestMakePostFromDict:
    def test_basic(self, db_session_fixture):
        event_data = _make_event_dict()
        result = crud.make_post_from_dict(event_data)

        assert "post" in result
        assert result["main_category_id"] == 1  # Концерты
        assert result["price_int"] == 500
