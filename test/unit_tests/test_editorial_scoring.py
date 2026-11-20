import json
from datetime import datetime, timedelta, timezone, time

import pytest
from davai_s_nami_bot.scoring import (
    calculate_score, apply_taste_to_breakdown, parse_breakdown,
    merge_editorial_result, routing_locked, can_return_to_channel, editorial_adjustment,
)
from davai_s_nami_bot import crud
from davai_s_nami_bot.database.models import Events2Posts, PostingTime


def test_full_recalculation_preserves_metadata_without_accumulating():
    event = {'title': 'Лекция', 'price_int': 0, 'score_breakdown': json.dumps(json.dumps({
        'editorial': {'score': 90}, 'manual': {'score': 100},
        'manual_transfer': {'target': 'ReadyToPost'}, 'publications': [{'kind': 'digest'}],
    }))}
    first = calculate_score(event, [], None, {"enabled": True})
    event['score_breakdown'] = first.to_json()
    second = calculate_score(event, [], None, {"enabled": True})
    assert first.total == second.total
    bd = parse_breakdown(second.to_json())
    assert bd['rating_adjustment'] == 10
    assert bd['publications'] == [{'kind': 'digest'}]
    assert routing_locked(bd)
    third = apply_taste_to_breakdown(bd, 80, {})
    assert apply_taste_to_breakdown(third, 80, {}) == third


def test_model_cannot_overwrite_manual_metadata_or_total():
    event = {'score_breakdown': {'total': 70, 'manual_transfer': None, 'manual': {'score': 100}, 'rating_adjustment': 5}}
    result = merge_editorial_result(event, {'prepared_text': 'Text', 'score': 100,
        'score_breakdown': {'manual': {}}, 'editorial': {'score': 90, 'reason': 'Facts'}})
    assert result['score'] == 75
    assert result['score_breakdown']['manual']['score'] == 100
    assert routing_locked(result['score_breakdown'])
    assert event['score_breakdown']['total'] == 70


@pytest.mark.parametrize('rating', [True, -1, 101, '100', float('nan'), None])
def test_invalid_ai_rating_has_no_effect(rating):
    result = merge_editorial_result({}, {'editorial': {'score': rating}})
    assert 'score_breakdown' not in result


def test_zero_is_a_valid_rating():
    result = merge_editorial_result({}, {'editorial': {'score': 0}})
    assert editorial_adjustment(result['score_breakdown']) == -5


def test_return_requires_provenance_and_respects_manual_transfer():
    bd = {'editorial': {'score': 100}}
    assert not can_return_to_channel('Posted', 90, bd)
    assert not can_return_to_channel('OnlyApi', 90, bd)
    bd['routing'] = {'reason': 'capacity'}
    assert can_return_to_channel('OnlyApi', 90, bd)
    bd['manual_transfer'] = False
    assert not can_return_to_channel('OnlyApi', 90, bd)
    bd.pop('manual_transfer')
    bd['publications'] = [{'kind': 'digest'}]
    assert can_return_to_channel('Posted', 90, bd)
    bd['publications'].append({'kind': 'individual'})
    assert not can_return_to_channel('Posted', 90, bd)


def event_row(idx, **overrides):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    fields = dict(id=idx, event_id=f'E{idx}', title='Concert', status='ReadyToPost',
                  city_id='spb', url='https://example.com', ticket_url='', source='TC',
                  queue=idx*2, score=80, from_date=now+timedelta(days=5),
                  to_date=now+timedelta(days=5, hours=2), score_breakdown={})
    fields.update(overrides)
    return Events2Posts(**fields)


def test_digest_records_provenance_without_overriding_manual_choice(db_session_fixture):
    row = event_row(9001, score_breakdown={'manual_transfer': {'target': 'ReadyToPost'}})
    db_session_fixture.add(row); db_session_fixture.commit()
    result = crud.mark_events_as_digested(db=db_session_fixture, event_ids=[row.id], post_url='https://t.me/test/1')
    assert result['moved'] == 0
    assert row.status == 'ReadyToPost'
    assert row.score_breakdown['publications'] == [{'kind': 'digest', 'url': 'https://t.me/test/1'}]


def test_individual_publication_blocks_later_return(db_session_fixture):
    row = event_row(9002)
    db_session_fixture.add(row); db_session_fixture.commit()
    crud.set_post_url(db=db_session_fixture, event_id=row.event_id, post_url='https://t.me/test/2')
    assert row.score_breakdown['publications'][0]['kind'] == 'individual'


def test_capacity_routing_respects_manual_marker(db_session_fixture):
    row = event_row(9003, score=1, score_breakdown={'manual_transfer': None})
    db_session_fixture.add(row); db_session_fixture.commit()
    assert crud.route_events_to_api(db=db_session_fixture, min_channel_queue=0) == []
    assert row.status == 'ReadyToPost'


def test_rebalance_dry_run_and_real_slot_selection(db_session_fixture, monkeypatch):
    anchor = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    incumbent = event_row(9010, score=60, from_date=anchor+timedelta(days=1, hours=12),
                          to_date=anchor+timedelta(days=1, hours=14))
    candidate = event_row(9011, status='OnlyApi', score=90,
                          score_breakdown={'editorial': {'score': 95}, 'routing': {'reason': 'capacity'}})
    db_session_fixture.add_all([incumbent, candidate]); db_session_fixture.commit()
    monkeypatch.setattr(crud, 'get_posting_slots', lambda **kw: [(0, 6, time(13))])
    monkeypatch.setattr(crud, 'find_embedding_duplicate', lambda **kw: None)
    cfg = {'protect_first': 0, 'horizon_days': 1}
    class Morning(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    monkeypatch.setattr(crud, 'datetime', Morning)
    monkeypatch.setattr(crud.settings, 'timezone', 'Europe/Moscow', raising=False)
    result = crud.rebalance_channel_queue(db=db_session_fixture, cfg=cfg, dry_run=True)
    assert incumbent.status == 'ReadyToPost' and candidate.status == 'OnlyApi'
    assert result['changes']
    result = crud.rebalance_channel_queue(db=db_session_fixture, cfg=cfg, dry_run=False)
    assert candidate.status == 'ReadyToPost'
    assert incumbent.status == 'OnlyApi'
    assert candidate.post_date < candidate.from_date


@pytest.mark.parametrize('status,score,editorial,publications,expected', [
    ('OnlyApi', 90, 74, [], False),
    ('OnlyApi', 74, 90, [], False),
    ('Posted', 80, 89, [{'kind': 'digest'}], False),
    ('Posted', 79, 90, [{'kind': 'digest'}], False),
    ('Posted', 80, 90, [{'kind': 'digest'}], True),
    ('Posted', 90, 100, [{'kind': 'digest'}, {'kind': 'legacy_unknown'}], False),
])
def test_quality_thresholds_and_unknown_publication(status, score, editorial, publications, expected):
    bd = {'editorial': {'score': editorial}, 'routing': {'reason': 'capacity'}, 'publications': publications}
    assert can_return_to_channel(status, score, bd) is expected
