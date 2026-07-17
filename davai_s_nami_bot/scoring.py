import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional


# Maps main_category_id → name (matches CATEGORIES_NAME in content_generator/services.py)
CATEGORY_ID_TO_NAME = {
    1: "Концерты",
    2: "Без категории",
    3: "Кино",
    4: "Лекции",
    5: "Культура",
    6: "Фестивали",
    7: "Театр",
    8: "Вечеринки",
    9: "Перфомансы",
    10: "Стэндап",
    11: "Выставки",
    12: "Спорт",
    13: "Мастер-классы",
}

DEFAULT_WEIGHTS = {
    "price": 15,
    "place": 15,
    "category": 20,
    "keywords": 15,
    "completeness": 15,
    "source": 10,
}

DEFAULT_PRICE_RANGES = [
    {"max": 0, "score": 100},
    {"max": 500, "score": 80},
    {"max": 1500, "score": 60},
    {"max": 3000, "score": 40},
    {"max": 99999, "score": 20},
]

# Weights for place reputation: positive history boosts, negative history penalises.
# A place's net reputation = sum(positive_status * weight) - sum(negative_status * weight),
# then mapped to a 0-100 place score. Posted carries full weight; queued/api-only count
# less; informed rejections (NOT auto-rejected by low score) and spam count as negatives.
DEFAULT_PLACE_REPUTATION_WEIGHTS = {
    "w_posted": 1.0,
    "w_ready": 0.5,
    "w_onlyapi": 0.3,
    "w_rejected": 1.0,
    "w_spam": 1.5,
}

DEFAULT_CATEGORY_SCORES = {
    6: 85,   # Фестивали
    9: 85,   # Перфомансы
    1: 80,   # Концерты
    3: 80,   # Кино
    11: 80,  # Выставки
    7: 75,   # Театр
    8: 75,   # Вечеринки
    10: 75,  # Стэндап
    4: 70,   # Лекции
    13: 65,  # Мастер-классы
    12: 50,  # Спорт
    5: 65,   # Культура
    2: 30,   # Без категории
}

DEFAULT_SOURCE_SCORES = {
    "timepad": 70,
    "radario": 60,
    "ticketscloud": 75,
    "qtickets": 65,
    "mts": 60,
    "culture.ru": 60,
    "vk": 45,
    "telegram": 40,
    "instagram": 40,
}

DEFAULT_BOOST_KEYWORDS = [
    "бесплатно", "премьера", "фестиваль", "открытие", "вернисаж",
    "дискусси", "лауреат", "впервые", "дебют", "импровизаци",
    "арт-резиденци", "арт-медиаци",
    "квартирник", "маркет", "open air", "кинопоказ", "фест", "филармо"
]
DEFAULT_PENALTY_KEYWORDS = [
    "реклама", "промо", "курс", "обучение", "вебинар", "тренинг",
    "конференци", "нетворкинг", "розыгрыш", "бизнес", "инвестиц",
    "корпоратив", "интенсив",
]


@dataclass
class ScoreBreakdown:
    price_score: int = 50
    place_score: int = 50
    category_score: int = 50
    keyword_score: int = 50
    completeness_score: int = 50
    source_score: int = 50
    repetition_penalty: int = 0
    place_queue_penalty: int = 0
    date_scarcity_boost: int = 0
    total: int = 50

    def to_json(self) -> str:
        return json.dumps({
            "price": self.price_score,
            "place": self.place_score,
            "category": self.category_score,
            "keywords": self.keyword_score,
            "completeness": self.completeness_score,
            "source": self.source_score,
            "repetition_penalty": self.repetition_penalty,
            "place_queue_penalty": self.place_queue_penalty,
            "date_scarcity_boost": self.date_scarcity_boost,
            "total": self.total,
        }, ensure_ascii=False)

    @classmethod
    def neutral(cls) -> "ScoreBreakdown":
        return cls()


def title_similarity(a: str, b: str) -> float:
    """Jaccard similarity between two titles based on words."""
    if not a or not b:
        return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


_TITLE_NOISE_WORDS = frozenset({
    # ticket/entry boilerplate
    "входной", "билет", "билеты", "вход", "абонемент", "запись", "бесплатный",
    # prepositions / conjunctions / particles
    "в", "во", "на", "и", "а", "с", "со", "к", "ко", "о", "об", "обо", "от",
    "до", "по", "за", "из", "изо", "у", "не", "для", "при", "под", "над",
    "про", "без", "или", "же", "то", "как",
    # month names (event dates inside titles: "Большой стендап 14 июня")
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
    "сентября", "октября", "ноября", "декабря",
    "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
    "сентябрь", "октябрь", "ноябрь", "декабрь",
})

# Common Russian case/plural endings, trimmed once from tokens longer than 4
# chars so that "выставка"/"выставку"/"выставке" all collapse to "выставк".
_STEM_ENDING_RE = re.compile(
    r"(ами|ями|ого|его|ому|ему|ыми|ими|ах|ях|ов|ев|ой|ей|ом|ем|ы|и|а|я|у|ю|е|о|ь)$"
)

# Anything that is not a letter: emoji, digits, punctuation, quotes.
_NON_LETTER_RE = re.compile(r"[^a-zа-яё]+")


def _light_stem(token: str) -> str:
    if len(token) > 4:
        return _STEM_ENDING_RE.sub("", token)
    return token


def normalize_title_tokens(title: Optional[str]) -> frozenset:
    """Title → set of stemmed core tokens (no emoji/digits/punctuation/noise words).

    AI prep adds emoji prefixes and scrapers add boilerplate ("Входной билет
    на ..."), so raw word comparison misses even identical titles. This strips
    all of that down to the words that actually identify the event.
    """
    if not title:
        return frozenset()
    cleaned = _NON_LETTER_RE.sub(" ", title.lower().replace("ё", "е"))
    return frozenset(
        _light_stem(tok)
        for tok in cleaned.split()
        if len(tok) > 1 and tok not in _TITLE_NOISE_WORDS
    )


def title_containment(a: Optional[str], b: Optional[str]) -> float:
    """Overlap of normalized title cores relative to the SHORTER one.

    1.0 when one core is a subset of the other — catches "Входной билет на
    выставку «Тело»" vs "Выставка Тело", unlike Jaccard which is diluted by
    the boilerplate words.
    """
    tokens_a = normalize_title_tokens(a)
    tokens_b = normalize_title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def _score_price(price_int, price_ranges: list) -> int:
    try:
        price_int = int(price_int) if price_int is not None else None
    except (ValueError, TypeError):
        return 65  # unknown price — neutral, not a penalty
    if price_int is None or price_int < 0:
        return 65  # unknown price — neutral, not a penalty
    for r in price_ranges:
        if price_int <= r["max"]:
            return r["score"]
    return 20


def _lookup_category_score(category_scores: dict, cat_id: int) -> int:
    """Lookup score by int key or string key (JSON always has string keys)."""
    return category_scores.get(cat_id, category_scores.get(str(cat_id), 30))


# Keywords for category inference (checked in order, first match wins).
# Each entry: (category_id, [keywords_to_match_in_title_or_text])
_CATEGORY_KEYWORDS: list[tuple[int, list[str]]] = [
    (10, ["стендап", "stand-up", "стэндап", "stand up"]),
    (9,  ["перформанс", "performance", "перформативн"]),
    (6,  ["фестиваль"]),
    (3,  ["кинопоказ", "кинофестиваль", "показ фильм", "показ кино", "короткометражн"]),
    (7,  ["спектакль", "театр", "постановк", "пьес"]),
    (11, ["выставка", "выставк", "экспозиц", "вернисаж"]),
    (4,  ["лекция", "лекци", "паблик-ток", "публичн", "дискусси", "доклад"]),
    (1,  ["концерт"]),
    (8,  ["вечеринк", "рейв", "пати ", "afterparty", "дискотек"]),
    (13, ["мастер-класс", "воркшоп", "workshop", "мастеркласс"]),
    (14, ["экскурси", "прогулк", "тур по"]),
    (3,  ["кино", "фильм", "показ"]),
    (12, ["турнир", "соревновани", "матч", "чемпионат"]),
]


def _guess_category_from_text(title: str, full_text: str) -> Optional[int]:
    """Infer category_id from keywords in title+text. Returns None if no match."""
    haystack = f"{title} {full_text}".lower()
    for cat_id, keywords in _CATEGORY_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return cat_id
    return None


def resolve_category_id(
    main_category_id: Optional[int],
    category_str: Optional[str],
    title: str = "",
    full_text: str = "",
) -> Optional[int]:
    """Resolve effective category_id: main_category_id → string match → keyword inference → None."""
    if main_category_id is not None:
        return main_category_id
    if category_str:
        for cat_id, cat_name in CATEGORY_ID_TO_NAME.items():
            if cat_name.lower() == category_str.strip().lower():
                return cat_id
    return _guess_category_from_text(title, full_text)


def _score_category(
    main_category_id: Optional[int],
    category_str: Optional[str],
    category_scores: dict,
    title: str = "",
    full_text: str = "",
) -> int:
    """Score by main_category_id → exact string match → keyword inference → 30."""
    cat_id = resolve_category_id(main_category_id, category_str, title, full_text)
    if cat_id is not None:
        return _lookup_category_score(category_scores, cat_id)
    return 30


def _place_net_reputation(rep: dict, weights: dict) -> float:
    """Weighted net reputation from a per-place status-count dict.

    rep keys: posted, ready, onlyapi (positive), rejected, spam (negative).
    """
    w = {**DEFAULT_PLACE_REPUTATION_WEIGHTS, **(weights or {})}
    return (
        w["w_posted"] * rep.get("posted", 0)
        + w["w_ready"] * rep.get("ready", 0)
        + w["w_onlyapi"] * rep.get("onlyapi", 0)
        - w["w_rejected"] * rep.get("rejected", 0)
        - w["w_spam"] * rep.get("spam", 0)
    )


def _score_place(
    place_id: Optional[int],
    place_post_counts: dict,
    place_reputation: Optional[dict] = None,
    weights: Optional[dict] = None,
) -> int:
    """Score place by reputation.

    If place_reputation is given ({place_id: {posted, ready, onlyapi, rejected, spam}}),
    use the weighted net reputation. Otherwise fall back to place_post_counts
    ({place_id: count_of_posted_events}) for backward compatibility.
    """
    if not place_id:
        return 20

    if place_reputation is not None:
        net = _place_net_reputation(place_reputation.get(place_id, {}), weights)
    else:
        net = place_post_counts.get(place_id, 0)

    if net >= 20:
        return 100
    if net >= 10:
        return 80
    if net >= 5:
        return 60
    if net >= 1:
        return 45
    if net >= 0:
        return 30  # known place but no track record yet
    if net >= -5:
        return 20  # mildly negative history
    return 10  # strongly negative history


def _score_keywords(
    title: str,
    full_text: str,
    boost_keywords: list,
    penalty_keywords: list,
    trusted_artists: list = None,
    trusted_organizers: list = None,
    trusted_boost: int = 25,
) -> int:
    """Base 50, +15 per boost keyword, -15 per penalty keyword, clamped 0-100.

    trusted_artists/trusted_organizers give +trusted_boost each (max once).
    """
    text = f"{title} {full_text}".lower()
    score = 50
    for kw in boost_keywords:
        if kw in text:
            score += 15
    for kw in penalty_keywords:
        if kw in text:
            score -= 15
    if trusted_artists:
        for artist in trusted_artists:
            if artist.lower() in text:
                score += trusted_boost
                break
    if trusted_organizers:
        for org in trusted_organizers:
            if org.lower() in text:
                score += trusted_boost
                break
    return max(0, min(100, score))


def _score_completeness(event_data: dict, place_id: Optional[int]) -> int:
    """Bonus for data completeness: image, price, address, place, full_text."""
    score = 0
    checks = {
        "image": 25,
        "address": 10,
        "full_text": 20,
    }
    for field, points in checks.items():
        val = event_data.get(field)
        if val and str(val).strip():
            score += points
    if place_id:
        score += 25
    if event_data.get("price_int") is not None and int(event_data.get("price_int"))>=0:
        score += 20
    return min(100, score)  # max possible ~90, cap at 100


def _score_source(source: Optional[str], source_scores: dict) -> int:
    if not source:
        return 40
    return source_scores.get(source.lower(), 40)


def _check_repetition(
    title: str,
    existing_titles: List[str],
    threshold: float = 0.8,
) -> bool:
    # Containment on normalized cores: catches date-suffixed series
    # ("Большой стендап 14 июня" vs "... 21 июня") and emoji-prefixed
    # prepared titles that word-level Jaccard misses.
    tokens = normalize_title_tokens(title)
    if not tokens:
        return False
    for existing in existing_titles:
        existing_tokens = normalize_title_tokens(existing)
        if not existing_tokens:
            continue
        containment = len(tokens & existing_tokens) / min(
            len(tokens), len(existing_tokens)
        )
        if containment > threshold:
            return True
    return False


def _is_exhibition_by_id(main_category_id: Optional[int]) -> bool:
    # Only trust main_category_id — raw category strings from scrapers are unreliable
    # (e.g. MTS labels master classes and quests as "Выставки").
    return main_category_id == 11


def calculate_score(
    event_data: dict,
    existing_titles: List[str],
    place_id: Optional[int],
    scoring_config: dict,
    place_post_counts: Optional[dict] = None,
    place_category_queue_counts: Optional[dict] = None,
    date_event_counts: Optional[dict] = None,
    place_reputation: Optional[dict] = None,
) -> ScoreBreakdown:
    """Calculate event score based on config weights.

    Parameters
    ----------
    event_data : dict
        Event fields: title, full_text, price_int, category,
        main_category_id, image, address, source.
    existing_titles : List[str]
        Recent event titles for repetition detection.
    place_id : int or None
        Resolved place_id.
    scoring_config : dict
        Scoring config block from settings.json.
    place_post_counts : dict or None
        {place_id: number_of_posted_events}. Legacy positive-only place reputation;
        used as a fallback when place_reputation is not provided.
    place_category_queue_counts : dict or None
        {(place_id, category_id): count} of ReadyToPost events per place+category.
        Used to penalise oversaturation from a single venue/genre.
    date_event_counts : dict or None
        {date: count} of events (Posted/ReadyToPost + NotApproved) per from_date.
        Used to boost events on sparse upcoming days.
    place_reputation : dict or None
        {place_id: {posted, ready, onlyapi, rejected, spam}} — weighted place
        reputation across statuses. Takes precedence over place_post_counts.
        Weights come from scoring_config["place_reputation"].

    Returns
    -------
    ScoreBreakdown
    """
    if not scoring_config or not scoring_config.get("enabled", False):
        return ScoreBreakdown.neutral()

    if place_post_counts is None:
        place_post_counts = {}

    weights = scoring_config.get("weights", DEFAULT_WEIGHTS)
    price_ranges = scoring_config.get("price_ranges", DEFAULT_PRICE_RANGES)
    category_scores = scoring_config.get(
        "category_scores", DEFAULT_CATEGORY_SCORES
    )
    source_scores = scoring_config.get("source_scores", DEFAULT_SOURCE_SCORES)
    boost_kw = scoring_config.get("boost_keywords", DEFAULT_BOOST_KEYWORDS)
    penalty_kw = scoring_config.get("penalty_keywords", DEFAULT_PENALTY_KEYWORDS)
    trusted_artists = scoring_config.get("trusted_artists", [])
    trusted_organizers = scoring_config.get("trusted_organizers", [])
    trusted_boost = scoring_config.get("trusted_boost", 25)
    repetition_penalty_val = scoring_config.get("repetition_penalty", -20)
    place_category_queue_limit = scoring_config.get("place_category_queue_limit", 6)
    place_category_queue_penalty = scoring_config.get("place_category_queue_penalty", -15)
    date_scarcity_window = scoring_config.get("date_scarcity_window_days", 10)
    date_scarcity_min_days = scoring_config.get("date_scarcity_min_days", 2)
    date_scarcity_threshold = scoring_config.get("date_scarcity_threshold", 5)
    date_scarcity_boost_val = scoring_config.get("date_scarcity_boost", 8)

    title = event_data.get("title", "") or ""
    full_text = event_data.get("full_text", "") or ""
    price_int = event_data.get("price_int")
    category_str = event_data.get("category")
    main_category_id = event_data.get("main_category_id")
    source = event_data.get("source")

    price_s = _score_price(price_int, price_ranges)
    category_s = _score_category(main_category_id, category_str, category_scores, title, full_text)
    place_reputation_weights = scoring_config.get("place_reputation", DEFAULT_PLACE_REPUTATION_WEIGHTS)
    place_s = _score_place(place_id, place_post_counts, place_reputation, place_reputation_weights)
    keyword_s = _score_keywords(
        title, full_text, boost_kw, penalty_kw,
        trusted_artists, trusted_organizers, trusted_boost,
    )
    completeness_s = _score_completeness(event_data, place_id)
    source_s = _score_source(source, source_scores)

    # Weighted sum
    w_total = sum(weights.values()) or 1
    raw = (
        price_s * weights.get("price", 15)
        + place_s * weights.get("place", 15)
        + category_s * weights.get("category", 20)
        + keyword_s * weights.get("keywords", 15)
        + completeness_s * weights.get("completeness", 15)
        + source_s * weights.get("source", 10)
    ) / w_total

    # Repetition penalty (title similarity)
    rep_penalty = 0
    if _check_repetition(title, existing_titles):
        rep_penalty = repetition_penalty_val

    # Place+category queue saturation penalty
    place_queue_pen = 0
    if place_category_queue_counts and place_id:
        effective_cat_id = resolve_category_id(main_category_id, category_str, title, full_text)
        if effective_cat_id is not None:
            queue_count = place_category_queue_counts.get((place_id, effective_cat_id), 0)
            if queue_count >= place_category_queue_limit:
                place_queue_pen = place_category_queue_penalty

    # Date scarcity boost: small boost for sparse upcoming days
    # Only applies when: min_days <= days_ahead <= window_days AND 1 <= day_count < threshold
    date_boost = 0
    if date_event_counts:
        from_date = event_data.get("from_date")
        if from_date is not None:
            if isinstance(from_date, datetime):
                event_day = from_date.date()
            else:
                event_day = from_date  # already a date
            today = datetime.now(timezone.utc).date()
            days_ahead = (event_day - today).days
            if date_scarcity_min_days <= days_ahead <= date_scarcity_window:
                day_count = date_event_counts.get(event_day, 0)
                if 1 <= day_count < date_scarcity_threshold:
                    date_boost = date_scarcity_boost_val

    total = max(0, min(100, int(raw + rep_penalty + place_queue_pen + date_boost)))

    return ScoreBreakdown(
        price_score=price_s,
        place_score=place_s,
        category_score=category_s,
        keyword_score=keyword_s,
        completeness_score=completeness_s,
        source_score=source_s,
        repetition_penalty=rep_penalty,
        place_queue_penalty=place_queue_pen,
        date_scarcity_boost=date_boost,
        total=total,
    )
