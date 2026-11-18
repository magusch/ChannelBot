from datetime import datetime, timedelta, timezone, time
from types import SimpleNamespace

import pytest
from davai_s_nami_bot import crud

NOW = datetime(2030, 1, 7, 6, tzinfo=timezone.utc)  # Monday, 09:00 Moscow
SLOTS = [(0, 6, time(13))]
CFG = {'protect_first': 0, 'horizon_days': 3, 'min_lead_hours': 24, 'min_runway_days': 0}


def event(idx, start_days=2, end_days=None, **kw):
    fields = dict(id=idx, title='Concert', category='Концерты', status='ReadyToPost', score=80,
                  queue=idx, post_date=None, score_breakdown={}, from_date=NOW+timedelta(days=start_days),
                  to_date=NOW+timedelta(days=end_days if end_days is not None else start_days, hours=3))
    fields.update(kw)
    return SimpleNamespace(**fields)


def plan(rows, cfg=None, slots=SLOTS):
    return crud._channel_schedule_plan(rows, slots, {**CFG, **(cfg or {})}, NOW)


def assigned(result):
    return {a['id']: datetime.fromisoformat(a['post_date']) for a in result['assignments']}


def test_urgent_event_fits_alongside_better_flexible_event():
    urgent = event(1, start_days=1.5, score=75)
    flexible = event(2, start_days=4, score=95)
    result = plan([flexible, urgent])
    dates = assigned(result)
    assert dates[1] < dates[2]
    assert len(dates) == 2
    assert dates[1] <= urgent.from_date-timedelta(hours=24)
    assert result['changes'] == []


def test_overflow_is_demoted_and_far_future_is_only_deferred():
    rows = [event(1, start_days=1.5, score=90), event(2, start_days=1.5, score=60),
            event(3, start_days=90, score=100)]
    result = plan(rows)
    assert set(assigned(result)) == {1}
    assert result['changes'] == [{'id': 2, 'status': 'OnlyApi', 'reason': 'capacity'}]


def test_protected_head_cannot_keep_a_date_after_event_end():
    row = event(1, start_days=2, post_date=NOW+timedelta(days=5))
    result = plan([row], {'protect_first': 2})
    assert assigned(result)[1] < row.from_date
    assert result['changes'] == []


def test_manual_event_without_valid_slot_is_not_transferred_or_scheduled_late():
    row = event(1, start_days=.01, score_breakdown={'manual_transfer': False})
    result = plan([row])
    assert result['assignments'] == []
    assert result['changes'] == []
    assert result['warnings'] == [{'id': 1, 'reason': 'protected_without_valid_slot'}]


def test_ongoing_exhibition_remains_postable_until_its_end():
    row = event(1, start_days=-20, end_days=10, category='Выставки')
    assert assigned(plan([row]))[1] < row.to_date


def test_manual_date_collision_is_resolved_without_changing_status():
    date = datetime(2030, 1, 7, 10, tzinfo=timezone.utc)
    rows = [event(i, start_days=3, post_date=date, score_breakdown={'manual_transfer': None}) for i in (1, 2)]
    result = plan(rows)
    assert len(set(assigned(result).values())) == 2
    assert result['changes'] == []


def test_slots_are_not_counted_after_they_passed_or_for_digest():
    result = plan([event(1, start_days=2)], slots=[(0, 0, time(8))])
    assert result['assignments'] == []


def test_posted_event_sent_early_still_owns_its_future_slot():
    occupied = event(1, start_days=3, status='Posted', post_date=datetime(2030, 1, 7, 10, tzinfo=timezone.utc))
    dates = assigned(plan([occupied, event(2, start_days=4)]))
    assert dates[2].date().day == 8


def test_scarce_weekday_slots_have_exact_dates():
    result = plan([event(1, start_days=4), event(2, start_days=4)], slots=[(1, 1, time(15))])
    dates = assigned(result)
    assert len(dates) == 1
    date = next(iter(dates.values()))
    assert date.weekday() == 1 and date.hour == 15


@pytest.mark.parametrize('slots,reason', [([], 'no_event_slots'), (None, 'slots_unavailable')])
def test_no_known_slots_never_falls_back_to_invented_capacity(db_session_fixture, monkeypatch, slots, reason):
    monkeypatch.setattr(crud, 'get_posting_slots', lambda **kw: slots)
    result = crud.schedule_channel_events(db=db_session_fixture, dry_run=False)
    assert result['skipped'] == reason and result['changes'] == []


def test_one_periodic_scheduler_and_catchup_entry(monkeypatch):
    from davai_s_nami_bot import celery_app, celery_tasks
    monkeypatch.setattr(celery_app.settings, 'route_unschedulable', {'enabled': True})
    beat = celery_app._city_beat_schedules()
    names = [entry['task'].split('.')[-1] for entry in beat.values()]
    assert names.count('route_unschedulable_events') == 1
    assert 'rebalance_channel_queue' not in names
    assert 'distribute_event_queue' not in names
    daily = [entry[0].split('.')[-1] for entry in celery_tasks._daily_task_schedule()]
    assert daily.count('route_unschedulable_events') == 1
    assert 'distribute_event_queue' not in daily


def test_schedule_endpoint_is_authenticated_and_defaults_to_preview(client, monkeypatch):
    called = []
    monkeypatch.setattr(crud, 'schedule_channel_events', lambda **kw: called.append(kw) or {'assignments': []})
    assert client.post('/api/events/schedule/channel/').status_code in (401, 403)
    response = client.post('/api/events/schedule/channel/', headers={'Authorization': 'Bearer test'})
    assert response.status_code == 200
    assert called == [{'dry_run': True, 'reselect': False}]
    assert client.post('/api/events/schedule/channel/?dry_run=false', headers={'Authorization': 'Bearer test'}).status_code == 200
    assert called[-1] == {'dry_run': False, 'reselect': False}


def test_sending_rejects_ended_events_but_allows_ongoing_exhibition(db_session_fixture, monkeypatch):
    from davai_s_nami_bot.database.models import Events2Posts
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(crud, 'datetime', Clock)
    monkeypatch.setattr(crud, 'get_posting_slots', lambda **kw: SLOTS)
    monkeypatch.setattr(crud.Event, 'from_database', lambda row: row)
    for idx, start, stop in [(1, -2, -1), (2, -.1, .1), (3, -10, 10)]:
        db_session_fixture.add(Events2Posts(id=idx, title='Event', event_id=f'e{idx}', queue=idx,
            status='ReadyToPost', city_id='spb', source='TC', url='https://example.com', ticket_url='',
            post_date=NOW, from_date=NOW+timedelta(days=start), to_date=NOW+timedelta(days=stop)))
    db_session_fixture.commit()
    assert [e.id for e in crud.get_event_to_post_now(db=db_session_fixture)] == [3]


def test_change_limit_does_not_write_half_a_schedule(db_session_fixture, monkeypatch):
    from davai_s_nami_bot.database.models import Events2Posts
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(crud, 'datetime', Clock)
    monkeypatch.setattr(crud, 'get_posting_slots', lambda **kw: SLOTS)
    for idx in (1, 2, 3):
        db_session_fixture.add(Events2Posts(id=idx, event_id=f'e{idx}', title='Concert', source='TC',
            status='ReadyToPost', city_id='spb', url='https://example.com', ticket_url='', queue=idx,
            score=90-idx*10, score_breakdown={}, from_date=NOW+timedelta(hours=9),
            to_date=NOW+timedelta(hours=12), post_date=NOW+timedelta(days=10)))
    db_session_fixture.commit()
    rows = db_session_fixture.query(Events2Posts).all()
    before = [(e.id, e.status, e.post_date, e.queue) for e in rows]
    cfg = {**CFG, 'horizon_days': 1, 'min_lead_hours': 0, 'limit': 1}
    result = crud.schedule_channel_events(db=db_session_fixture, cfg=cfg, dry_run=False)
    assert result['skipped'] == 'change_limit'
    assert [(e.id, e.status, e.post_date, e.queue) for e in rows] == before
    cfg['limit'] = 0
    result = crud.schedule_channel_events(db=db_session_fixture, cfg=cfg, dry_run=False)
    assert len(result['routed_ids']) == 2
    assert crud.schedule_channel_events(db=db_session_fixture, cfg=cfg, dry_run=False)['changes'] == []


def test_legacy_task_names_share_the_same_planner(monkeypatch):
    from davai_s_nami_bot import celery_tasks
    called = []
    monkeypatch.setattr(crud, 'get_posting_slots', lambda *args, **kw: SLOTS)
    monkeypatch.setattr(crud, 'schedule_channel_events', lambda **kw: called.append(kw) or {'assignments': []})
    celery_tasks.route_unschedulable_events(dry_run=True)
    celery_tasks.rebalance_channel_queue(dry_run=True)
    celery_tasks.distribute_event_queue()
    assert [call['dry_run'] for call in called] == [True, True, False]


def test_two_manual_exhibition_slots_survive_daily_reselection():
    first = datetime(2030, 1, 8, 10, tzinfo=timezone.utc)
    second = datetime(2030, 1, 9, 10, tzinfo=timezone.utc)
    kim = event(18276, start_days=-10, end_days=40, queue=28932, score=64, post_date=first,
                score_breakdown={'manual_schedule': {'post_date': first.isoformat(), 'queue': 28932}})
    aivazovsky = event(18619, start_days=-20, end_days=90, queue=28934, score=48, post_date=second,
                      score_breakdown={'manual_schedule': {'post_date': second.isoformat(), 'queue': 28934}})
    result = plan([kim, aivazovsky, event(3, start_days=4, score=100)], {'protect_first': 2})
    assert assigned(result)[18276] == first
    assert assigned(result)[18619] == second
    assert result['changes'] == []
    assert assigned(plan([kim, aivazovsky], {'protect_first': 2}))[18276] == first


def test_intraday_fill_keeps_dates_and_does_not_promote_api():
    first = datetime(2030, 1, 8, 10, tzinfo=timezone.utc)
    second = datetime(2030, 1, 9, 10, tzinfo=timezone.utc)
    rows = [event(1, start_days=4, score=30, post_date=first),
            event(2, start_days=5, score=100, post_date=second),
            event(3, start_days=5, status='OnlyApi', score=100,
                  score_breakdown={'editorial': {'score': 100}, 'routing': {'reason': 'capacity'}})]
    result = plan(rows, {'preserve_schedule': True})
    assert assigned(result) == {1: first, 2: second}
    assert result['changes'] == []


def test_intraday_repair_does_not_steal_another_valid_slot():
    reserved = datetime(2030, 1, 7, 10, tzinfo=timezone.utc)
    rows = [event(1, start_days=4, queue=1, post_date=NOW+timedelta(days=20)),
            event(2, start_days=4, queue=2, post_date=reserved)]
    result = plan(rows, {'preserve_schedule': True})
    assert assigned(result)[2] == reserved
    assert assigned(result)[1] > reserved
