"""Adaptive scoring: learn source_scores, category_scores from real posting decisions.

Runs weekly. Compares posted events (Events2Posts with post_url) vs rejected
(EventsNotApproved not extracted/approved, or stale 'new' older than 7 days).
Saves learned config to Redis; calculate_score reads it as overlay on settings.json.
"""

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

REDIS_KEY = "adaptive_scoring_config"
REDIS_TTL_SECONDS = 60 * 60 * 24 * 10  # 10 days (survives if task fails once)

# Statuses that count as "rejected" (negative signal)
NEGATIVE_STATUSES = {"rejected", "not_event", "spam", "duplicate"}
# 'new' older than this many days is treated as ignored (negative)
STALE_NEW_DAYS = 7

# Min samples per group to trust the adaptive score
MIN_SAMPLES = 5

# Floor/ceiling for adaptive scores (don't go to extremes)
SCORE_FLOOR = 30
SCORE_CEILING = 95

# Word frequency analysis settings
MIN_WORD_LEN = 5
MIN_WORD_OCCURRENCES = 8
MIN_RATIO_BOOST = 2.5   # word must appear 2.5x more in posted
MIN_RATIO_PENALTY = 2.5  # word must appear 2.5x more in rejected
MAX_SUGGESTED_KEYWORDS = 8

# Words to never suggest as keywords
_STOP_WORDS = {
    # Pronouns, particles, prepositions
    "этот", "того", "будет", "было", "быть", "есть", "если",
    "только", "более", "после", "через", "когда", "всех", "свой",
    "свои", "всего", "очень", "каждый", "также", "может",
    "можно", "нужно", "весь", "этого", "были", "этих", "этом",
    "которые", "который", "которой", "которая", "которого",
    "такие", "такой", "такая", "таких", "будут", "стать",
    "себя", "тебя", "него", "ними", "нами", "вами",
    "однако", "поэтому", "потому", "именно", "просто",
    "самые", "самый", "самая", "самое", "самых",
    "другие", "другой", "другая", "других",
    "первый", "первая", "первые", "первого",
    "новый", "новая", "новые", "нового", "новых",
    "один", "одна", "одно", "одной", "одного",
    "этой", "этим", "этому", "свою", "своей", "своих",
    "наши", "ваши", "ваше", "наших", "ваших",
    # Time
    "время", "день", "дней", "года", "году", "месяц", "часов",
    "минут", "неделю", "сегодня", "завтра", "вчера",
    "марта", "апреля", "января", "февраля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
    # Cities
    "петербург", "санкт", "казань", "москва", "россия",
    "петербурга", "казани", "москвы", "россии",
    # Event generic
    "мероприятие", "событие", "события", "вход", "билет", "билеты",
    "место", "адрес", "начало", "стоимость", "цена",
    "регистрация", "подробнее", "ссылка", "информация",
    "программа", "участие", "участники",
    # HTML/tech
    "https", "http", "www", "nbsp", "quot", "amp",
    # Verbs/adjectives too generic
    "делают", "делать", "сделать", "могли", "хотел", "хотели",
    "стали", "стало", "стала", "пять", "четыре", "шесть",
    "большой", "большая", "большие", "большого",
    "многие", "многих", "много",
    "каждую", "каждой", "каждого",
    "меняется", "становится", "получить", "смысла",
    "совершенно", "настоящ", "прекрасн",
    # Too specific / inflected forms (noise)
    "штрихов", "шутками", "категорий", "залами", "старинной",
    "сообщество",
}


def calculate_adaptive_config(
    positive_events: list[dict],
    negative_events: list[dict],
    current_config: dict,
) -> dict:
    """Calculate adaptive scoring overrides from real data.

    Parameters
    ----------
    positive_events : list[dict]
        Events from Events2Posts (posted or approved).
    negative_events : list[dict]
        Events from EventsNotApproved that were rejected/ignored.
    current_config : dict
        Current scoring config from settings.json.

    Returns
    -------
    dict
        Adaptive overrides: source_scores, category_scores, suggested_boost, suggested_penalty.
    """
    result = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "positive_count": len(positive_events),
        "negative_count": len(negative_events),
    }

    # 1. Adaptive source_scores
    source_scores = _calc_adaptive_source_scores(
        positive_events, negative_events, current_config.get("source_scores", {})
    )
    if source_scores:
        result["source_scores"] = source_scores

    # 2. Adaptive category_scores
    category_scores = _calc_adaptive_category_scores(
        positive_events, negative_events, current_config.get("category_scores", {})
    )
    if category_scores:
        result["category_scores"] = category_scores

    # 3. Keyword suggestions (not auto-applied, just stored for review)
    suggested_boost, suggested_penalty = _suggest_keywords(
        positive_events, negative_events, current_config
    )
    if suggested_boost:
        result["suggested_boost_keywords"] = suggested_boost
    if suggested_penalty:
        result["suggested_penalty_keywords"] = suggested_penalty

    return result


def _calc_adaptive_source_scores(
    positive: list[dict], negative: list[dict], base_scores: dict
) -> dict:
    """Calculate source_scores based on acceptance rate."""
    pos_by_source = Counter(e.get("source", "").lower() for e in positive if e.get("source"))
    neg_by_source = Counter(e.get("source", "").lower() for e in negative if e.get("source"))

    all_sources = set(pos_by_source) | set(neg_by_source)
    adaptive = {}

    for source in all_sources:
        pos_count = pos_by_source.get(source, 0)
        neg_count = neg_by_source.get(source, 0)
        total = pos_count + neg_count

        if total < MIN_SAMPLES:
            continue

        rate = pos_count / total
        # Map acceptance rate to score: 0% → FLOOR, 100% → CEILING
        score = int(SCORE_FLOOR + rate * (SCORE_CEILING - SCORE_FLOOR))
        adaptive[source] = score

    return adaptive if adaptive else {}


def _calc_adaptive_category_scores(
    positive: list[dict], negative: list[dict], base_scores: dict
) -> dict:
    """Calculate category_scores based on acceptance rate per main_category_id."""
    pos_by_cat = Counter()
    neg_by_cat = Counter()

    for e in positive:
        cat_id = e.get("main_category_id")
        if cat_id is not None:
            pos_by_cat[str(cat_id)] += 1

    for e in negative:
        cat_id = e.get("main_category_id")
        if cat_id is not None:
            neg_by_cat[str(cat_id)] += 1

    all_cats = set(pos_by_cat) | set(neg_by_cat)
    adaptive = {}

    for cat_id in all_cats:
        pos_count = pos_by_cat.get(cat_id, 0)
        neg_count = neg_by_cat.get(cat_id, 0)
        total = pos_count + neg_count

        if total < MIN_SAMPLES:
            continue

        rate = pos_count / total
        score = int(SCORE_FLOOR + rate * (SCORE_CEILING - SCORE_FLOOR))
        adaptive[cat_id] = score

    return adaptive if adaptive else {}


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer: lowercase, only cyrillic/latin words."""
    if not text:
        return []
    return [w for w in re.findall(r"[а-яёa-z]{%d,}" % MIN_WORD_LEN, text.lower())
            if w not in _STOP_WORDS]


def _suggest_keywords(
    positive: list[dict], negative: list[dict], config: dict
) -> tuple[list[str], list[str]]:
    """Find words enriched in positive vs negative events."""
    existing_boost = set(config.get("boost_keywords", []))
    existing_penalty = set(config.get("penalty_keywords", []))
    existing_all = existing_boost | existing_penalty

    pos_words = Counter()
    neg_words = Counter()

    for e in positive:
        text = f"{e.get('title', '')} {e.get('full_text', '')}"
        for w in set(_tokenize(text)):
            pos_words[w] += 1

    for e in negative:
        text = f"{e.get('title', '')} {e.get('full_text', '')}"
        for w in set(_tokenize(text)):
            neg_words[w] += 1

    n_pos = max(len(positive), 1)
    n_neg = max(len(negative), 1)

    boost_candidates = []
    penalty_candidates = []

    all_words = set(pos_words) | set(neg_words)
    for w in all_words:
        # Skip words that are already in config or too rare
        if w in existing_all:
            continue

        pc = pos_words.get(w, 0)
        nc = neg_words.get(w, 0)

        if pc + nc < MIN_WORD_OCCURRENCES:
            continue

        # Normalize by group size
        pos_rate = pc / n_pos
        neg_rate = nc / n_neg

        if pos_rate > 0 and neg_rate > 0:
            ratio = pos_rate / neg_rate
            if ratio >= MIN_RATIO_BOOST:
                boost_candidates.append((w, ratio, pc))
            elif 1 / ratio >= MIN_RATIO_PENALTY:
                penalty_candidates.append((w, 1 / ratio, nc))
        elif pc >= MIN_WORD_OCCURRENCES and nc == 0:
            boost_candidates.append((w, 99.0, pc))
        elif nc >= MIN_WORD_OCCURRENCES and pc == 0:
            penalty_candidates.append((w, 99.0, nc))

    # Sort by ratio descending, take top N
    boost_candidates.sort(key=lambda x: (-x[1], -x[2]))
    penalty_candidates.sort(key=lambda x: (-x[1], -x[2]))

    return (
        [w for w, _, _ in boost_candidates[:MAX_SUGGESTED_KEYWORDS]],
        [w for w, _, _ in penalty_candidates[:MAX_SUGGESTED_KEYWORDS]],
    )


def merge_adaptive_config(base_config: dict, adaptive: Optional[dict]) -> dict:
    """Merge adaptive overrides into base scoring config.

    Adaptive values override base for source_scores and category_scores.
    Keywords are NOT auto-merged (only suggested).
    """
    if not adaptive:
        return base_config

    merged = dict(base_config)

    if "source_scores" in adaptive:
        merged_sources = dict(base_config.get("source_scores", {}))
        merged_sources.update(adaptive["source_scores"])
        merged["source_scores"] = merged_sources

    if "category_scores" in adaptive:
        merged_cats = dict(base_config.get("category_scores", {}))
        merged_cats.update(adaptive["category_scores"])
        merged["category_scores"] = merged_cats

    return merged


def save_to_redis(redis_client, adaptive_config: dict):
    """Save adaptive config to Redis."""
    redis_client.setex(
        REDIS_KEY,
        REDIS_TTL_SECONDS,
        json.dumps(adaptive_config, ensure_ascii=False),
    )
    log.info(f"Adaptive scoring saved to Redis (TTL={REDIS_TTL_SECONDS}s)")


def load_from_redis(redis_client) -> Optional[dict]:
    """Load adaptive config from Redis. Returns None if not found."""
    data = redis_client.get(REDIS_KEY)
    if not data:
        return None
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return None
