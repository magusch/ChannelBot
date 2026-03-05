import json
from dataclasses import dataclass
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
    14: "Экскурсии",
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
    14: 50,  # Экскурсии
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
]
DEFAULT_PENALTY_KEYWORDS = [
    "реклама", "промо", "курс", "обучение", "вебинар", "тренинг", "конкурс", "розыгрыш",
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


def _score_price(price_int: Optional[int], price_ranges: list) -> int:
    if price_int is None or price_int < 0:
        return 40
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


def _score_category(
    main_category_id: Optional[int],
    category_str: Optional[str],
    category_scores: dict,
    title: str = "",
    full_text: str = "",
) -> int:
    """Score by main_category_id → exact string match → keyword inference → 30."""
    if main_category_id is not None:
        return _lookup_category_score(category_scores, main_category_id)

    # Exact string match against our taxonomy
    if category_str:
        for cat_id, cat_name in CATEGORY_ID_TO_NAME.items():
            if cat_name.lower() == category_str.strip().lower():
                return _lookup_category_score(category_scores, cat_id)

    # Keyword inference from title + full_text
    guessed_id = _guess_category_from_text(title, full_text)
    if guessed_id is not None:
        return _lookup_category_score(category_scores, guessed_id)

    return 30


def _score_place(place_id: Optional[int], place_post_counts: dict) -> int:
    """Score place by reputation (number of posted events).

    place_post_counts: {place_id: count_of_posted_events}
    """
    if not place_id:
        return 20
    count = place_post_counts.get(place_id, 0)
    if count >= 20:
        return 100
    if count >= 10:
        return 80
    if count >= 5:
        return 60
    if count >= 1:
        return 45
    return 30  # known place but no posts yet


def _score_keywords(
    title: str,
    full_text: str,
    boost_keywords: list,
    penalty_keywords: list,
) -> int:
    """Base 50, +10 per boost keyword, -10 per penalty keyword, clamped 0-100."""
    text = f"{title} {full_text}".lower()
    score = 50
    for kw in boost_keywords:
        if kw in text:
            score += 10
    for kw in penalty_keywords:
        if kw in text:
            score -= 10
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
    if event_data.get("price_int") is not None and event_data.get("price_int")>=0:
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
    for existing in existing_titles:
        if title_similarity(title, existing) > threshold:
            return True
    return False


def _is_exhibition_by_id(main_category_id: Optional[int]) -> bool:
    return main_category_id == 11


def _is_exhibition(
    main_category_id: Optional[int], category_str: Optional[str]
) -> bool:
    # Only trust main_category_id — raw category strings from scrapers are unreliable
    # (e.g. MTS labels master classes and quests as "Выставки")
    return main_category_id == 11


def calculate_score(
    event_data: dict,
    existing_titles: List[str],
    place_id: Optional[int],
    scoring_config: dict,
    place_post_counts: Optional[dict] = None,
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
        {place_id: number_of_posted_events} for place reputation.

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
    repetition_penalty_val = scoring_config.get("repetition_penalty", -20)

    title = event_data.get("title", "") or ""
    full_text = event_data.get("full_text", "") or ""
    price_int = event_data.get("price_int")
    category_str = event_data.get("category")
    main_category_id = event_data.get("main_category_id")
    source = event_data.get("source")

    price_s = _score_price(price_int, price_ranges)
    category_s = _score_category(main_category_id, category_str, category_scores, title, full_text)
    place_s = _score_place(place_id, place_post_counts)
    keyword_s = _score_keywords(title, full_text, boost_kw, penalty_kw)
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

    # Repetition penalty
    rep_penalty = 0
    if _check_repetition(title, existing_titles):
        rep_penalty = repetition_penalty_val

    total = max(0, min(100, int(raw + rep_penalty)))

    return ScoreBreakdown(
        price_score=price_s,
        place_score=place_s,
        category_score=category_s,
        keyword_score=keyword_s,
        completeness_score=completeness_s,
        source_score=source_s,
        repetition_penalty=rep_penalty,
        total=total,
    )
