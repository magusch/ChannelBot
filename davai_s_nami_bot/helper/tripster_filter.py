"""Selection policy for Tripster excursions.

Tripster returns roughly a thousand experiences for a single week in St.
Petersburg, and the overwhelming majority is mass-market sightseeing: the
same "first acquaintance with the city" walk sold by two hundred guides,
running several times a day. The channel's audience already lives here, so
what we want is the opposite end of that catalogue — excursions that are
rare, specific, and about a layer of the city a local has not already seen
from a tour boat.

Everything here is a pure function over the raw partner-API payload. That is
deliberate: `escraper`'s `Tripster.parse()` collapses each experience into the
16 common event tags and drops exactly the fields the selection depends on
(`rating`, `review_count`, `popularity`, `schedule`, `tags`, `duration`,
`guide`, `max_persons`, `type`). So filtering has to happen before parsing,
and keeping it free of network and DB access makes it testable without a
Tripster token.

The funnel, in order:

1. `active`          — status/upcoming sessions sanity check
2. `type`            — group tours only; a private guide-for-hire is a
                       different product (and its price is per group)
3. `rating`          — quality floor (Tripster ratings are inflated, so the
                       bar sits high)
4. `reviews`         — has an actual track record
5. `sessions`        — anti-conveyor: something running twice a day every day
                       is a factory, not a find
6. `price`           — locals do not pay tourist money for a walk
7. `duration`        — a 10-hour slot means an out-of-town bus tour
8. `group_size`      — 40 seats means a bus
9. `out_of_town`     — Peterhof/Kronstadt/Vyborg are day trips for visitors
10. `touristy`       — "обзорная", "главные достопримечательности", ...
11. `local_topic`    — optional whitelist: keep only recognizably local themes
12. `similar_title`  — collapse near-identical listings (many guides sell the
                       same walk under the same name)
13. `per_guide`      — one guide should not fill the feed with a catalogue
14. `limit`          — final cap, best-ranked first

Stages 1-11 are per-item and independent; 12-14 look across the surviving set.
"""

from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytz

from ..scoring import title_containment

MSK = pytz.timezone("Europe/Moscow")

# Ordered so a preview can print the funnel the way items actually flow.
FUNNEL_STAGES = (
    "active",
    "type",
    "movement",
    "rating",
    "reviews",
    "sessions",
    "price",
    "duration",
    "group_size",
    "out_of_town",
    "touristy",
    "local_topic",
    "similar_title",
    "per_guide",
    "limit",
)

DEFAULT_EXCLUDED_MOVEMENT_TYPES = [
    "bus",
    "motorship",
    "speedboat",
    "watership",
    "car",
]

DEFAULT_OUT_OF_TOWN_KEYWORDS = [
    "петергоф",
    "кронштадт",
    "пушкин",
    "царское село",
    "павловск",
    "гатчина",
    "ораниенбаум",
    "стрельна",
    "выборг",
    "шлиссельбург",
    "старая ладога",
    "тихвин",
    "валаам",
    "карели",
    "рускеала",
    "ивангород",
    "копорье",
    "приорат",
    "линдуловск",
    "комарово",
    "репино",
    "сестрорецк",
    "зеленогорск",
    "токсово",
    "новгород",
    "псков",
    "оредеж",
    "саблино",
    "вырица",
    "сиверск",
    "приозерск",
]

DEFAULT_TOURISTY_KEYWORDS = [
    "обзорн",
    "первое знакомство",
    "знакомство с городом",
    "знакомство с петербург",
    "главные достопримечательност",
    "must see",
    "must-see",
    "визитная карточка",
    "весь петербург",
    "весь питер",
    "сердце петербурга",
    "за один день",
    "за 1 день",
    "экспресс-тур",
    "теплоход",
    "речная прогулка",
    "по рекам и каналам",
    "кораблик",
    "развод мостов",
    "разводные мосты",
    "автобусн",
    "на автобусе",
    "фотопрогулка",
    "фотосесси",
    "инстаграм",
    "instagram",
    "для туристов",
    "первый раз в петербурге",
    "квест",
    "без очереди",
    # Must-see museums and palaces. These pass the structural gates (they are
    # `movement_type: museum`, well-rated and cheap enough), but a ticketed
    # Hermitage or Yusupov Palace tour is the definition of the thing a
    # long-time resident is not looking for — and the catalogue carries half a
    # dozen near-identical variants of each.
    "эрмитаж",
    "юсуповск",
    "у юсуповых",
    "зимнего дворца",
    "зимний дворец",
    "исаакиевск",
    "спас на крови",
    "петропавловск",
    "аврора",
    "кунсткамера",
    "екатерининский дворец",
    "янтарная комната",
    "мариинский",
]

DEFAULT_LOCAL_TOPIC_KEYWORDS = [
    "двор",
    "парадн",
    "коммуналк",
    "модерн",
    "конструктивизм",
    "авангард",
    "доходн",
    "изнутри",
    "закулис",
    "мастерск",
    "ателье",
    "кладбищ",
    "промышленн",
    "завод",
    "фабрик",
    "газгольдер",
    "порт",
    "гастро",
    "рюмочн",
    "бар",
    "рынок",
    "блокад",
    "ленинград",
    "советск",
    "андеграунд",
    "стрит-арт",
    "мурал",
    "граффити",
    "архитектур",
    "реставрац",
    "подземн",
    "диггер",
    "бомбоубежищ",
    "метро",
    "коломна",
    "петроградск",
    "васильевск",
    "охта",
    "купчино",
    "нарвск",
    "обводн",
    "лигово",
    "новая голландия",
    "севкабель",
    "апраксин",
    "литейн",
    "пески",
    "не для туристов",
    "нетуристическ",
    "локальн",
    "местн",
]

DEFAULT_TRIPSTER_FILTER: Dict[str, Any] = {
    "min_rating": 4.75,
    "min_reviews": 3,
    "max_sessions": 0,
    "types": ["group"],
    "excluded_movement_types": DEFAULT_EXCLUDED_MOVEMENT_TYPES,
    "max_price": 3500,
    "max_duration_hours": 5.0,
    "max_group_size": 25,
    "out_of_town_keywords": DEFAULT_OUT_OF_TOWN_KEYWORDS,
    "touristy_keywords": DEFAULT_TOURISTY_KEYWORDS,
    "require_local_topic": False,
    "local_topic_keywords": DEFAULT_LOCAL_TOPIC_KEYWORDS,
    "similar_title_threshold": 0.75,
    "max_per_guide": 3,
    "limit": 250,
}

def _text_of(item: Dict[str, Any], *keys: str) -> str:
    """Lowercased concatenation of the given fields (missing ones ignored)."""
    parts = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts).lower()


def _topic_haystack(item: Dict[str, Any]) -> str:
    """Text used for keyword gates: title, tagline, annotation, tags, meeting point.

    `description` is deliberately excluded — it is long enough that almost any
    keyword appears somewhere in it, which would make every gate fire.
    """
    haystack = _text_of(item, "title", "tagline", "annotation")
    tags = item.get("tags")
    if isinstance(tags, (list, tuple)):
        for tag in tags:
            if isinstance(tag, str):
                haystack += " " + tag.lower()
            elif isinstance(tag, dict):
                if (tag.get("flags") or {}).get("is_auto"):
                    continue
                for key in ("name", "title", "name_ru", "slug"):
                    if isinstance(tag.get(key), str):
                        haystack += " " + tag[key].lower()
                        break
    meeting = item.get("meeting_point")
    if isinstance(meeting, dict) and isinstance(meeting.get("text"), str):
        haystack += " " + meeting["text"].lower()
    return haystack


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_value(item: Dict[str, Any]) -> Optional[float]:
    price = item.get("price")
    if not isinstance(price, dict):
        return None
    return _as_float(price.get("value"))


def session_count(
    item: Dict[str, Any], *, now: Optional[datetime] = None, days: int = 7
) -> int:
    """Number of upcoming sessions inside the scrape window.

    The API hands back every known future slot, so counting the whole list
    would punish an excursion that simply publishes its schedule far ahead.
    Only slots within `days` are counted, which makes the number comparable
    to "how often does this run this week".
    """
    schedule = item.get("schedule")
    if not isinstance(schedule, dict):
        return 0
    upcoming = schedule.get("upcoming_events")
    if not isinstance(upcoming, (list, tuple)):
        return 0

    now = now or datetime.now(MSK)
    horizon = now + timedelta(days=days)
    count = 0
    for raw in upcoming:
        if not isinstance(raw, str):
            continue
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            continue
        # Tripster sends both naive and tz-aware stamps; compare in MSK.
        if moment.tzinfo is None:
            moment = MSK.localize(moment)
        if now <= moment <= horizon:
            count += 1
    return count


def _guide_key(item: Dict[str, Any]) -> str:
    guide = item.get("guide")
    if not isinstance(guide, dict):
        return ""
    for key in ("id", "slug", "first_name", "name"):
        value = guide.get(key)
        if value:
            return f"{key}:{value}"
    return ""


def reject_reason(
    item: Dict[str, Any],
    cfg: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    days: int = 7,
) -> Optional[str]:
    """Return the funnel stage that rejects this item, or None if it passes.

    Missing values never reject on their own: Tripster omits `rating` on new
    listings and `duration` on some formats, and treating absence as failure
    would quietly filter by "how completely the guide filled the form".
    """
    if item.get("status") != "active":
        return "active"
    schedule = item.get("schedule") or {}
    if not schedule.get("upcoming_events"):
        return "active"

    types = cfg.get("types")
    if types and item.get("type") and item["type"] not in types:
        return "type"

    excluded_movement = cfg.get("excluded_movement_types") or []
    if item.get("movement_type") in excluded_movement:
        return "movement"

    rating = _as_float(item.get("rating"))
    min_rating = cfg.get("min_rating")
    if min_rating and rating is not None and rating < min_rating:
        return "rating"

    reviews = _as_float(item.get("review_count"))
    min_reviews = cfg.get("min_reviews")
    if min_reviews and (reviews or 0) < min_reviews:
        return "reviews"

    max_sessions = cfg.get("max_sessions")
    if max_sessions:
        sessions = session_count(item, now=now, days=days)
        if sessions > max_sessions:
            return "sessions"

    max_price = cfg.get("max_price")
    price = _price_value(item)
    if max_price and price is not None and price > max_price:
        return "price"

    max_duration = cfg.get("max_duration_hours")
    duration = _as_float(item.get("duration"))
    if max_duration and duration is not None and duration > max_duration:
        return "duration"

    max_group = cfg.get("max_group_size")
    group_size = _as_float(item.get("max_persons"))
    if max_group and group_size is not None and group_size > max_group:
        return "group_size"

    haystack = _topic_haystack(item)
    if any(kw in haystack for kw in cfg.get("out_of_town_keywords") or []):
        return "out_of_town"
    if any(kw in haystack for kw in cfg.get("touristy_keywords") or []):
        return "touristy"
    if cfg.get("require_local_topic"):
        if not any(kw in haystack for kw in cfg.get("local_topic_keywords") or []):
            return "local_topic"

    return None


def rank_score(
    item: Dict[str, Any],
    cfg: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    days: int = 7,
) -> float:
    """Ordering for the final cap: proven, rare and affordable first.

    Rarity is a positive term rather than only a gate — between two equally
    well-reviewed walks the one that runs once a week is the more interesting
    find than the one running five times.
    """
    rating = _as_float(item.get("rating")) or 4.5
    reviews = _as_float(item.get("review_count")) or 0
    sessions = session_count(item, now=now, days=days) or 1
    price = _price_value(item)

    quality = (rating - 4.0) / 1.0  # 4.0 → 0, 5.0 → 1
    # Reviews saturate: 10 vs 20 matters, 300 vs 600 does not.
    track_record = min(reviews, 100) / 100
    rarity = 1.0 / sessions
    max_price = cfg.get("max_price") or 0
    if price is None or not max_price:
        affordability = 0.5
    else:
        affordability = max(0.0, 1.0 - price / max_price)

    return 0.4 * quality + 0.25 * track_record + 0.25 * rarity + 0.1 * affordability


def _collapse_similar(
    items: List[Dict[str, Any]], threshold: float
) -> Tuple[List[Dict[str, Any]], int]:
    """Drop listings whose title core repeats one already kept.

    Reuses the same containment metric as the event dedup, so "Дворы и
    парадные Петербурга" and "Парадные и дворы Петербурга" collapse to one.
    Items arrive best-first, so the survivor is the better-ranked one.
    """
    if not threshold:
        return items, 0
    kept: List[Dict[str, Any]] = []
    for item in items:
        title = item.get("title") or ""
        if any(
            title_containment(title, other.get("title") or "") > threshold
            for other in kept
        ):
            continue
        kept.append(item)
    return kept, len(items) - len(kept)


def _cap_per_guide(
    items: List[Dict[str, Any]], max_per_guide: int
) -> Tuple[List[Dict[str, Any]], int]:
    """Keep at most `max_per_guide` experiences from the same guide."""
    if not max_per_guide:
        return items, 0
    seen: Counter = Counter()
    kept: List[Dict[str, Any]] = []
    for item in items:
        key = _guide_key(item)
        if key:
            if seen[key] >= max_per_guide:
                continue
            seen[key] += 1
        kept.append(item)
    return kept, len(items) - len(kept)


def select_experiences(
    items: Iterable[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
    days: int = 7,
) -> Tuple[List[Dict[str, Any]], "OrderedDict[str, int]"]:
    """Narrow a raw Tripster search payload down to the interesting excursions.

    Returns the surviving raw items (best-ranked first) and a funnel of how
    many were dropped at each stage — the funnel is what makes the thresholds
    tunable instead of guessed.
    """
    cfg = {**DEFAULT_TRIPSTER_FILTER, **(config or {})}
    dropped: Counter = Counter()

    survivors: List[Dict[str, Any]] = []
    total = 0
    for item in items:
        total += 1
        if not isinstance(item, dict):
            dropped["active"] += 1
            continue
        reason = reject_reason(item, cfg, now=now, days=days)
        if reason:
            dropped[reason] += 1
            continue
        survivors.append(item)

    survivors.sort(key=lambda it: rank_score(it, cfg, now=now, days=days), reverse=True)

    survivors, dup_dropped = _collapse_similar(
        survivors, cfg.get("similar_title_threshold") or 0
    )
    dropped["similar_title"] = dup_dropped

    survivors, guide_dropped = _cap_per_guide(survivors, cfg.get("max_per_guide") or 0)
    dropped["per_guide"] = guide_dropped

    limit = cfg.get("limit") or 0
    if limit and len(survivors) > limit:
        dropped["limit"] = len(survivors) - limit
        survivors = survivors[:limit]

    funnel: "OrderedDict[str, int]" = OrderedDict()
    funnel["input"] = total
    for stage in FUNNEL_STAGES:
        funnel[stage] = dropped.get(stage, 0)
    funnel["selected"] = len(survivors)
    return survivors, funnel
