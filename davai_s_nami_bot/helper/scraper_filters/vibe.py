"""Selection policy for the Vibe city feed (Ticketscloud events of every organizer).

The feed is a whole-city catalogue (~600 TC events in 20 days for SPb), so
before anything reaches NotApproved the obvious mass market is dropped:
over-priced shows (incl. lounge tables), candle-light / cover-band /
paint-and-wine formats, and organizers whose output we already marked as spam.
A per-organizer cap keeps one big seller (Stage StandUp alone lists 100+
shows a month) from filling a run. The feed comes sorted by Vibe rating, so the
cap keeps an organizer's best-rated events; known ids are skipped on the next
run (every few days), so the rest get their turn.

Category exclusion happens in escraper itself (``exclude_categories``) — it is
the only filter applied before the TC event page is requested.

All functions are pure — tested without network or DB.
"""

from typing import Dict, List, Optional

DEFAULTS = {
    "max_price": 5000,
    "exclude_title_keywords": [
        "при свечах",
        "artvibes",
        "арт-вечеринка",
        "рисуем",
        "быстрых свиданий",
        "дискотек",
        "кавер",
    ],
    "exclude_places": [],
    "exclude_organizers": [],
    "max_per_organizer": 10,
}

#: List settings come in two forms: ``<key>`` replaces the default list,
#: ``extra_<key>`` is appended to it (default or replaced).
LIST_KEYS = ("exclude_title_keywords", "exclude_places", "exclude_organizers")

#: Vibe categories dropped inside escraper, before the TC page request.
DEFAULT_EXCLUDE_CATEGORIES = ["Детям"]

FUNNEL_STAGES = ("price", "title", "place", "organizer", "per_organizer")

#: GeoNames ids Vibe uses as city_id, by the bot's city code.
CITY_IDS = {"spb": "498817", "kzn": "551487", "msk": "524901"}


def merged_list(cfg: dict, key: str, default: List[str]) -> List[str]:
    """``cfg[key]`` (or ``default``) plus ``cfg["extra_" + key]``, de-duplicated."""
    base = cfg.get(key)
    values = list(default if base is None else base)
    values += cfg.get(f"extra_{key}") or []
    return list(dict.fromkeys(values))


def resolve_config(cfg: Optional[dict] = None) -> dict:
    """Defaults + overrides, with the replace/extend rule for list settings."""
    cfg = cfg or {}
    resolved = {**DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS}}
    for key in LIST_KEYS:
        resolved[key] = merged_list(cfg, key, DEFAULTS[key])
    return resolved


def rejection_reason(event: dict, cfg: dict) -> Optional[str]:
    """Stage name that drops the event, or None if it passes the per-event gates.

    ``event`` keys: title, place_name, price_int (None = unknown), org_id.
    A missing value never rejects on its own.
    """
    price = event.get("price_int")
    if cfg.get("max_price") and price is not None and price > cfg["max_price"]:
        return "price"

    title = (event.get("title") or "").lower()
    if any(word.lower() in title for word in cfg.get("exclude_title_keywords") or []):
        return "title"

    place = (event.get("place_name") or "").lower()
    if any(word.lower() in place for word in cfg.get("exclude_places") or []):
        return "place"

    org_id = event.get("org_id")
    if org_id and org_id in set(cfg.get("exclude_organizers") or []):
        return "organizer"
    return None


class VibeFilter:
    """Stateful filter for one scraper run: per-event gates + per-organizer cap."""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = resolve_config(cfg)
        self.per_organizer: Dict[str, int] = {}
        self.funnel: Dict[str, int] = {stage: 0 for stage in FUNNEL_STAGES}
        self.passed = 0

    def accept(self, event: dict) -> bool:
        reason = rejection_reason(event, self.cfg)
        if reason is None:
            org_id = event.get("org_id")
            cap = self.cfg.get("max_per_organizer") or 0
            if org_id and cap:
                if self.per_organizer.get(org_id, 0) >= cap:
                    reason = "per_organizer"
                else:
                    self.per_organizer[org_id] = self.per_organizer.get(org_id, 0) + 1
        if reason is not None:
            self.funnel[reason] += 1
            return False
        self.passed += 1
        return True

    def summary(self) -> str:
        dropped = ", ".join(f"{k} -{v}" for k, v in self.funnel.items() if v)
        return f"passed {self.passed}" + (f" ({dropped})" if dropped else "")
