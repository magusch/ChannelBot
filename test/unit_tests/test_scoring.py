import json
import pytest

from davai_s_nami_bot.scoring import (
    ScoreBreakdown,
    apply_taste_to_breakdown,
    calculate_score,
    normalize_title_tokens,
    parse_breakdown,
    title_containment,
    title_similarity,
    _score_completeness,
    _score_source,
    _score_place,
    _score_category,
    CATEGORY_ID_TO_NAME,
)


ENABLED_CONFIG = {
    "enabled": True,
    "weights": {
        "price": 15,
        "place": 15,
        "category": 20,
        "keywords": 15,
        "completeness": 15,
        "source": 10,
    },
    "repetition_penalty": -20,
    "price_ranges": [
        {"max": 0, "score": 100},
        {"max": 500, "score": 80},
        {"max": 1500, "score": 60},
        {"max": 3000, "score": 40},
        {"max": 99999, "score": 20},
    ],
    "category_scores": {
        1: 90,   # Концерты
        8: 85,   # Вечеринки
        6: 85,   # Фестивали
        11: 65,  # Выставки
        2: 30,   # Без категории
        4: 55,   # Лекции
    },
    "source_scores": {
        "timepad": 70,
        "radario": 70,
        "tg": 40,
        "vk": 45,
    },
    "boost_keywords": ["бесплатно", "премьера", "фестиваль", "открытие"],
    "penalty_keywords": ["реклама", "промо", "курс", "обучение", "вебинар"],
    "repetition_window_days": 14,
    "exhibition_repetition_penalty": -30,
}

# Same config but with string keys (as loaded from JSON)
ENABLED_CONFIG_STR_KEYS = {
    **ENABLED_CONFIG,
    "category_scores": {
        "1": 90, "8": 85, "6": 85,
        "11": 65, "2": 30, "4": 55,
    },
}


# --- Price scoring ---

def test_free_event_high_price_score():
    event = {"title": "Концерт", "price_int": 0, "main_category_id": 1}
    result = calculate_score(event, [], place_id=1, scoring_config=ENABLED_CONFIG)
    assert result.price_score == 100


def test_expensive_event_low_price_score():
    event = {"title": "Концерт", "price_int": 5000, "main_category_id": 1}
    result = calculate_score(event, [], place_id=1, scoring_config=ENABLED_CONFIG)
    assert result.price_score == 20


# --- Category scoring ---

def test_category_scoring_by_id():
    """main_category_id is used for scoring."""
    event_concert = {"title": "X", "price_int": 0, "main_category_id": 1}
    event_unknown = {"title": "X", "price_int": 0, "main_category_id": 2}

    r1 = calculate_score(event_concert, [], place_id=None, scoring_config=ENABLED_CONFIG)
    r2 = calculate_score(event_unknown, [], place_id=None, scoring_config=ENABLED_CONFIG)

    assert r1.category_score == 90
    assert r2.category_score == 30
    assert r1.total > r2.total


def test_category_fallback_to_string():
    """When main_category_id is None, fall back to category string."""
    event = {"title": "X", "price_int": 0, "category": "Концерты"}
    r = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG)
    assert r.category_score == 90


def test_category_string_keys_from_json():
    """JSON has string keys like '1', '8' etc."""
    event = {"title": "X", "price_int": 0, "main_category_id": 1}
    r = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG_STR_KEYS)
    assert r.category_score == 90


def test_unknown_category_string():
    """Random category string from scraper → default 30."""
    event = {"title": "X", "price_int": 0, "category": "Какая-то ерунда от сайта"}
    r = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG)
    assert r.category_score == 30


# --- Keywords ---

def test_keyword_boost_and_penalty():
    event_boost = {
        "title": "Бесплатно премьера фильма",
        "full_text": "",
        "price_int": 0,
        "main_category_id": 3,
    }
    event_penalty = {
        "title": "Курс обучение вебинар",
        "full_text": "",
        "price_int": 0,
        "main_category_id": 3,
    }

    r_boost = calculate_score(event_boost, [], place_id=None, scoring_config=ENABLED_CONFIG)
    r_penalty = calculate_score(event_penalty, [], place_id=None, scoring_config=ENABLED_CONFIG)

    assert r_boost.keyword_score > 50
    assert r_penalty.keyword_score < 50


# --- Repetition ---

def test_repetition_penalty():
    event = {"title": "Концерт группы Кино в клубе", "price_int": 500, "main_category_id": 1}
    existing = ["Концерт группы Кино в клубе"]

    r_no_rep = calculate_score(event, [], place_id=1, scoring_config=ENABLED_CONFIG)
    r_with_rep = calculate_score(event, existing, place_id=1, scoring_config=ENABLED_CONFIG)

    assert r_with_rep.repetition_penalty == -20
    assert r_with_rep.total < r_no_rep.total


def test_title_similarity():
    assert title_similarity("Концерт группы Кино", "Концерт группы Кино") == 1.0
    assert title_similarity("Концерт группы Кино", "Выставка картин Дали") < 0.2
    assert title_similarity("", "Что-то") == 0.0
    assert title_similarity("", "") == 0.0

    sim = title_similarity("Концерт группы Кино в клубе", "Концерт группы Кино")
    assert 0.5 < sim < 1.0


def test_normalize_title_tokens_strips_emoji_and_boilerplate():
    # AI prep adds emoji, scrapers add ticket boilerplate — neither is identity.
    assert normalize_title_tokens("💭 Выставка «Так не бывает»") == \
        normalize_title_tokens("Выставка Так не бывает")
    assert "билет" not in normalize_title_tokens("Входной билет на выставку «Тело»")
    assert normalize_title_tokens("") == frozenset()
    assert normalize_title_tokens(None) == frozenset()


def test_normalize_title_tokens_collapses_case_forms():
    # "выставку"/"выставка" must land on the same stem.
    a = normalize_title_tokens("Входной билет на выставку «Тело»")
    b = normalize_title_tokens("Выставка Тело")
    assert a == b


def test_title_containment_catches_boilerplate_wrapped_titles():
    # The exact production case: Timepad re-issues an exhibition with a
    # "Входной билет на ..." wrapper; Jaccard fails, containment must not.
    assert title_containment(
        "Входной билет на выставку «Тело»", "Выставка Тело"
    ) == 1.0
    assert title_containment(
        "💭 Выставка «Так не бывает»", "🏺 Выставка «Так не бывает»"
    ) == 1.0
    # Date-suffixed series instances compare as the same core.
    assert title_containment(
        "Большой стендап 14 июня", "Большой стендап 21 июля"
    ) == 1.0
    # Different events stay apart.
    assert title_containment("Концерт группы Кино", "Выставка картин Дали") < 0.5
    assert title_containment("", "Что-то") == 0.0


def test_repetition_detected_for_date_suffixed_series():
    event = {
        "title": "Большой стендап 21 июня",
        "price_int": 500,
        "main_category_id": 10,
    }
    existing = ["🎤 Большой стендап 14 июня"]

    result = calculate_score(event, existing, place_id=1, scoring_config=ENABLED_CONFIG)
    assert result.repetition_penalty == -20


# --- taste component --------------------------------------------------------

TASTE_CONFIG = {**ENABLED_CONFIG, "weights": {**ENABLED_CONFIG["weights"], "taste": 20}}


def test_taste_score_moves_total_when_present():
    event = {"title": "Концерт X", "price_int": 500, "main_category_id": 1}

    base = calculate_score(event, [], place_id=1, scoring_config=TASTE_CONFIG)
    liked = calculate_score(
        event, [], place_id=1, scoring_config=TASTE_CONFIG, taste_score=100
    )
    disliked = calculate_score(
        event, [], place_id=1, scoring_config=TASTE_CONFIG, taste_score=0
    )

    assert liked.total > base.total > disliked.total
    assert liked.taste_score == 100
    # None keeps the component (and its weight) out entirely.
    assert base.taste_score is None
    assert '"taste": null' in base.to_json()


def test_parse_breakdown_handles_double_encoded_json():
    inner = {"price": 80, "place": 70, "total": 75}
    assert parse_breakdown(json.dumps(inner)) == inner
    # Historical rows: JSON string containing JSON.
    assert parse_breakdown(json.dumps(json.dumps(inner))) == inner
    assert parse_breakdown(None) is None
    assert parse_breakdown("not json") is None


def test_apply_taste_to_breakdown_recomputes_total_idempotently():
    stored = json.dumps({
        "price": 80, "place": 60, "category": 90, "keywords": 50,
        "completeness": 75, "source": 70, "repetition_penalty": 0,
        "place_queue_penalty": 0, "date_scarcity_boost": 0, "total": 71,
    })

    lifted = apply_taste_to_breakdown(stored, 100, TASTE_CONFIG)
    assert lifted["taste"] == 100
    assert lifted["total"] > 71

    # Re-applying a different taste rebuilds from base components, not from
    # the already-adjusted total.
    dropped = apply_taste_to_breakdown(json.dumps(lifted), 0, TASTE_CONFIG)
    assert dropped["total"] < 71

    # Malformed / incomplete breakdowns are refused rather than guessed.
    assert apply_taste_to_breakdown(json.dumps({"price": 80}), 50, TASTE_CONFIG) is None
    assert apply_taste_to_breakdown(None, 50, TASTE_CONFIG) is None


def test_exhibition_duplicate():
    event = {"title": "Выставка Дали", "price_int": 500, "main_category_id": 11}
    existing = ["Выставка Дали"]

    result = calculate_score(event, existing, place_id=1, scoring_config=ENABLED_CONFIG)
    assert result.repetition_penalty == -20


def test_exhibition_duplicate_by_category_string():
    """Exhibition detected via category string fallback."""
    event = {"title": "Выставка Дали", "price_int": 500, "category": "Выставки"}
    existing = ["Выставка Дали"]

    result = calculate_score(event, existing, place_id=1, scoring_config=ENABLED_CONFIG)
    assert result.repetition_penalty == -20


# --- Place reputation ---

def test_place_reputation_scoring():
    """Place with more posted events gets higher score."""
    counts = {1: 25, 2: 3, 3: 0}

    assert _score_place(1, counts) == 100  # 25 posts → 100
    assert _score_place(2, counts) == 45   # 3 posts → 45
    assert _score_place(3, counts) == 30   # 0 posts → 30
    assert _score_place(None, counts) == 20  # no place → 20
    assert _score_place(999, counts) == 30   # unknown place_id, 0 posts → 30


def test_place_reputation_in_total():
    """Place with history boosts total score."""
    event = {"title": "Test", "price_int": 0, "main_category_id": 1, "source": "timepad"}
    counts_good = {42: 20}
    counts_none = {}

    r_good = calculate_score(event, [], place_id=42, scoring_config=ENABLED_CONFIG, place_post_counts=counts_good)
    r_new = calculate_score(event, [], place_id=42, scoring_config=ENABLED_CONFIG, place_post_counts=counts_none)

    assert r_good.place_score > r_new.place_score
    assert r_good.total > r_new.total


# --- Weighted place reputation (positive + negative) ---

WEIGHTS = {
    "w_posted": 1.0, "w_ready": 0.5, "w_onlyapi": 0.3,
    "w_rejected": 1.0, "w_spam": 1.5,
}


def test_place_reputation_positive_weights():
    # 20 posted → net 20 → 100
    rep = {1: {"posted": 20}}
    assert _score_place(1, {}, place_reputation=rep, weights=WEIGHTS) == 100
    # 10 ready → net 5.0 → 60
    rep = {1: {"ready": 10}}
    assert _score_place(1, {}, place_reputation=rep, weights=WEIGHTS) == 60
    # 10 onlyapi → net 3.0 → 45
    rep = {1: {"onlyapi": 10}}
    assert _score_place(1, {}, place_reputation=rep, weights=WEIGHTS) == 45


def test_place_reputation_negative_drags_below_neutral():
    # No positives, 5 rejected → net -5 → 20
    rep = {1: {"rejected": 5}}
    assert _score_place(1, {}, place_reputation=rep, weights=WEIGHTS) == 20
    # 4 spam → net -6 → 10 (strongly negative)
    rep = {1: {"spam": 4}}
    assert _score_place(1, {}, place_reputation=rep, weights=WEIGHTS) == 10


def test_place_reputation_net_mix():
    # 10 posted - 5 spam*1.5 = 10 - 7.5 = 2.5 → 45
    rep = {1: {"posted": 10, "spam": 5}}
    assert _score_place(1, {}, place_reputation=rep, weights=WEIGHTS) == 45


def test_place_reputation_unknown_place_neutral():
    rep = {1: {"posted": 20}}
    # place 999 not in rep → net 0 → 30
    assert _score_place(999, {}, place_reputation=rep, weights=WEIGHTS) == 30


def test_place_reputation_fallback_to_post_counts():
    # When place_reputation is None, falls back to place_post_counts (legacy).
    assert _score_place(1, {1: 20}) == 100
    assert _score_place(1, {1: 0}) == 30


# --- Source reliability ---

def test_source_scoring():
    assert _score_source("timepad", ENABLED_CONFIG["source_scores"]) == 70
    assert _score_source("tg", ENABLED_CONFIG["source_scores"]) == 40
    assert _score_source("unknown_source", ENABLED_CONFIG["source_scores"]) == 40
    assert _score_source(None, ENABLED_CONFIG["source_scores"]) == 40


def test_source_affects_total():
    event_tp = {"title": "Test", "price_int": 0, "main_category_id": 1, "source": "timepad"}
    event_tg = {"title": "Test", "price_int": 0, "main_category_id": 1, "source": "tg"}

    r_tp = calculate_score(event_tp, [], place_id=None, scoring_config=ENABLED_CONFIG)
    r_tg = calculate_score(event_tg, [], place_id=None, scoring_config=ENABLED_CONFIG)

    assert r_tp.source_score == 70
    assert r_tg.source_score == 40
    assert r_tp.total >= r_tg.total


# --- Completeness ---

def test_completeness_full_event():
    event = {
        "title": "Test",
        "image": "https://example.com/img.jpg",
        "price": "500 руб",
        "price_int": 500,
        "address": "Невский 1",
        "full_text": "Описание мероприятия...",
    }
    score = _score_completeness(event, place_id=42)
    # image=25 + address=10 + full_text=20 + place=25 + price=20 = 100
    assert score == 100


def test_completeness_empty_event():
    event = {"title": "Test"}
    score = _score_completeness(event, place_id=None)
    assert score == 0


def test_completeness_partial_event():
    event = {
        "title": "Test",
        "image": "https://example.com/img.jpg",
        "full_text": "Описание",
    }
    score = _score_completeness(event, place_id=None)
    # image=25 + full_text=20 = 45
    assert score == 45


def test_completeness_affects_total():
    event_full = {
        "title": "Test", "price_int": 0, "main_category_id": 1,
        "image": "img.jpg", "price": "free", "address": "addr",
        "full_text": "text", "source": "timepad",
    }
    event_empty = {
        "title": "Test", "price_int": 0, "main_category_id": 1,
        "source": "timepad",
    }

    r_full = calculate_score(event_full, [], place_id=42, scoring_config=ENABLED_CONFIG)
    r_empty = calculate_score(event_empty, [], place_id=None, scoring_config=ENABLED_CONFIG)

    assert r_full.completeness_score > r_empty.completeness_score
    assert r_full.total > r_empty.total


# --- Disabled / neutral ---

def test_scoring_disabled():
    event = {"title": "Test", "price_int": 0, "main_category_id": 1}
    disabled_config = {"enabled": False}

    result = calculate_score(event, [], place_id=1, scoring_config=disabled_config)
    assert result.total == 50

    result_empty = calculate_score(event, [], place_id=1, scoring_config={})
    assert result_empty.total == 50


# --- ScoreBreakdown ---

def test_score_breakdown_to_json():
    breakdown = ScoreBreakdown(
        price_score=100, place_score=60, category_score=90,
        keyword_score=70, completeness_score=80, source_score=65,
        repetition_penalty=0, total=80,
    )
    data = json.loads(breakdown.to_json())
    assert data["price"] == 100
    assert data["completeness"] == 80
    assert data["source"] == 65
    assert data["total"] == 80


def test_place_category_queue_saturation():
    """Events are penalised when place+category queue already at or above limit."""
    event = {"title": "Большой стендап", "price_int": 500, "main_category_id": 10, "source": "timepad"}
    queue_counts_empty = {}
    queue_counts_full = {(42, 10): 6}   # 6 standup events from place 42 already queued

    r_no_sat = calculate_score(
        event, [], place_id=42, scoring_config=ENABLED_CONFIG,
        place_category_queue_counts=queue_counts_empty,
    )
    r_sat = calculate_score(
        event, [], place_id=42, scoring_config=ENABLED_CONFIG,
        place_category_queue_counts=queue_counts_full,
    )

    assert r_no_sat.place_queue_penalty == 0
    assert r_sat.place_queue_penalty == -15
    assert r_sat.total < r_no_sat.total


def test_place_category_queue_different_category_not_penalised():
    """Different category at same place is NOT penalised."""
    event = {"title": "Концерт джаза", "price_int": 500, "main_category_id": 1, "source": "timepad"}
    queue_counts = {(42, 10): 10}  # standup saturated, but this is a concert (cat 1)

    result = calculate_score(
        event, [], place_id=42, scoring_config=ENABLED_CONFIG,
        place_category_queue_counts=queue_counts,
    )
    assert result.place_queue_penalty == 0


def test_place_category_queue_custom_limit():
    """Custom limit via scoring_config."""
    config = {**ENABLED_CONFIG, "place_category_queue_limit": 3, "place_category_queue_penalty": -20}
    event = {"title": "Взрослый стендап", "price_int": 300, "main_category_id": 10}
    queue_counts = {(42, 10): 3}  # exactly at limit

    result = calculate_score(event, [], place_id=42, scoring_config=config,
                             place_category_queue_counts=queue_counts)
    assert result.place_queue_penalty == -20


def _scoring_today():
    """Today as calculate_score sees it.

    The boost measures `days_ahead` against `datetime.now(timezone.utc).date()`,
    so offsets built from the local `date.today()` are off by one whenever the
    local date and the UTC date disagree — which silently flipped these
    assertions on a UTC+7 machine for seven hours a day.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()


def test_date_scarcity_boost_applies():
    """Boost applied when 1 <= day_count < threshold and within window."""
    from datetime import timedelta
    event_day = _scoring_today() + timedelta(days=5)
    event = {"title": "Стендап шоу", "price_int": 500, "main_category_id": 10,
             "from_date": event_day}
    date_counts_sparse = {event_day: 2}   # only 2 events on that day
    date_counts_full = {event_day: 8}     # 8 events — above threshold
    date_counts_empty = {}                # no data — date not scraped yet

    r_sparse = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG,
                               date_event_counts=date_counts_sparse)
    r_full = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG,
                             date_event_counts=date_counts_full)
    r_empty = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG,
                              date_event_counts=date_counts_empty)

    assert r_sparse.date_scarcity_boost == 8
    assert r_full.date_scarcity_boost == 0    # enough events, no boost
    assert r_empty.date_scarcity_boost == 0   # no data yet, no boost
    assert r_sparse.total > r_full.total


def test_date_scarcity_boost_not_too_soon():
    """No boost for events within min_days from today (tomorrow/day after)."""
    from datetime import timedelta
    tomorrow = _scoring_today() + timedelta(days=1)
    event = {"title": "Концерт", "price_int": 500, "main_category_id": 1,
             "from_date": tomorrow}
    date_counts = {tomorrow: 1}  # sparse, but too soon

    result = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG,
                             date_event_counts=date_counts)
    assert result.date_scarcity_boost == 0


def test_date_scarcity_boost_outside_window():
    """No boost for events beyond the window (> 10 days)."""
    from datetime import timedelta
    far_day = _scoring_today() + timedelta(days=15)
    event = {"title": "Концерт", "price_int": 500, "main_category_id": 1,
             "from_date": far_day}
    date_counts = {far_day: 1}

    result = calculate_score(event, [], place_id=None, scoring_config=ENABLED_CONFIG,
                             date_event_counts=date_counts)
    assert result.date_scarcity_boost == 0


def test_total_clamped_0_100():
    event = {
        "title": "реклама промо курс обучение вебинар",
        "full_text": "",
        "price_int": 50000,
        "main_category_id": 2,
        "source": "telegram",
    }
    existing = ["реклама промо курс обучение вебинар"]
    result = calculate_score(event, existing, place_id=None, scoring_config=ENABLED_CONFIG)
    assert 0 <= result.total <= 100
