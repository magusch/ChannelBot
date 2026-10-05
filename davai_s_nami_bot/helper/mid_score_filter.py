"""Selection policy for mid-score NotApproved events that go to OnlyApi.

Events scored 55-69 sit in NotApproved as 'new' and nobody reviews them, while
the zone holds plenty of decent lectures, concerts and markets. Only events
with independent evidence of quality are let through, and only into OnlyApi
(API and digests), never into the channel queue:

- ``listed``  — the organizer is in ``onlyapi_organizers``: its events belong
  in the API but not in the channel (Stage StandUp series, far-off venues);
- ``trusted`` — the organizer had at least ``min_posted`` really posted events
  and not a single Spam mark within ``history_days``;
- ``taste``   — the kNN taste component is high (the event is close to what we
  post) and the category is known.

Any Spam mark of the organizer in the window blocks the trusted and taste
paths: spam comes in bursts from single organizers, and a previously clean
history did not predict it. A per-organizer cap and a near-identical
title check keep a series (one show repeated 30 times) from flooding the API;
listed organizers get a larger cap, since their whole programme is meant for
the API.

All functions are pure — tested without a database.
"""

import re
from typing import Dict, Iterable, List, Optional, Tuple

from ..scoring import title_containment

DEFAULTS = {
    "min_score": 55,
    "max_score": 69,
    "listed_min_score": 40,
    "min_taste": 75,
    "min_posted": 3,
    "history_days": 180,
    "max_per_organizer": 3,
    "max_per_listed_organizer": 10,
    "similar_title_threshold": 0.8,
    "limit": 30,
    "onlyapi_organizers": [],
    # Formats the channel's audience (17-29) never wants; frequent in manual Spam.
    "exclude_title_keywords": [
        "для детей",
        "детск",
        "для малышей",
        "разговорный клуб",
        "быстрых свиданий",
    ],
}

UNCATEGORIZED_CATEGORY_ID = 2

_ORGANIZER_HOST_RE = re.compile(
    r"https?://([^./]+)\.(?:timepad\.ru|ticketscloud\.org)", re.IGNORECASE
)


def organizer_key(
    url: Optional[str], ticket_url: Optional[str] = None, place_id: Optional[int] = None
) -> Optional[str]:
    """Stable organizer id: Timepad/Ticketscloud subdomain, else 'place:<id>'.

    The subdomain is the organizer account; the place is a weaker fallback
    (one venue hosts many organizers) used for sources without accounts.
    """
    for link in (url, ticket_url):
        match = _ORGANIZER_HOST_RE.match(link or "")
        if match:
            return match.group(1).lower()
    if place_id is not None:
        return f"place:{place_id}"
    return None


def organizer_stats(rows: Iterable[dict]) -> Dict[str, Dict[str, int]]:
    """Count really posted events and Spam marks per organizer.

    Rows are Events2Posts dicts with url/ticket_url/place_id/status/post_url.
    'Posted' counts only with a post_url (a real publication).
    """
    stats: Dict[str, Dict[str, int]] = {}
    for row in rows:
        key = organizer_key(row.get("url"), row.get("ticket_url"), row.get("place_id"))
        if key is None:
            continue
        entry = stats.setdefault(key, {"posted": 0, "spam": 0})
        status = row.get("status")
        if status == "Posted" and row.get("post_url"):
            entry["posted"] += 1
        elif status == "Spam":
            entry["spam"] += 1
    return stats


def classify(event: dict, stats: Dict[str, Dict[str, int]], cfg: dict) -> Optional[str]:
    """Return the reason the event qualifies ('listed'/'trusted'/'taste') or None.

    ``event`` needs score, title, taste, category_id and url/ticket_url/place_id.
    ``category_id`` is the resolved category (None if unknown).
    """
    score = event.get("score")
    if score is None or score > cfg["max_score"]:
        return None

    title = (event.get("title") or "").lower()
    if any(word.lower() in title for word in cfg.get("exclude_title_keywords") or []):
        return None

    key = organizer_key(event.get("url"), event.get("ticket_url"), event.get("place_id"))
    listed = {k.lower() for k in cfg.get("onlyapi_organizers") or []}
    if key is not None and key in listed:
        return "listed" if score >= cfg["listed_min_score"] else None

    if score < cfg["min_score"]:
        return None

    org = stats.get(key, {"posted": 0, "spam": 0}) if key else {"posted": 0, "spam": 0}
    if org["spam"] > 0:
        return None
    if org["posted"] >= cfg["min_posted"]:
        return "trusted"

    taste = event.get("taste")
    category_id = event.get("category_id")
    if (
        taste is not None
        and taste >= cfg["min_taste"]
        and category_id is not None
        and category_id != UNCATEGORIZED_CATEGORY_ID
    ):
        return "taste"
    return None


def select_candidates(
    events: List[dict], stats: Dict[str, Dict[str, int]], cfg: Optional[dict] = None
) -> List[Tuple[dict, str]]:
    """Pick events to route, best score first, capped per organizer and in total."""
    cfg = {**DEFAULTS, **(cfg or {})}
    per_organizer: Dict[str, int] = {}
    titles_by_organizer: Dict[str, List[str]] = {}
    selected: List[Tuple[dict, str]] = []

    ordered = sorted(events, key=lambda e: (-(e.get("score") or 0), e.get("id") or 0))
    for event in ordered:
        if len(selected) >= cfg["limit"]:
            break
        reason = classify(event, stats, cfg)
        if reason is None:
            continue
        key = organizer_key(
            event.get("url"), event.get("ticket_url"), event.get("place_id")
        )
        if key is not None:
            cap = (
                cfg["max_per_listed_organizer"]
                if reason == "listed"
                else cfg["max_per_organizer"]
            )
            if per_organizer.get(key, 0) >= cap:
                continue
            # One show on many dates: a single entry is enough for the API.
            title = event.get("title") or ""
            seen_titles = titles_by_organizer.setdefault(key, [])
            if any(
                title_containment(title, seen) >= cfg["similar_title_threshold"]
                for seen in seen_titles
            ):
                continue
            seen_titles.append(title)
            per_organizer[key] = per_organizer.get(key, 0) + 1
        selected.append((event, reason))
    return selected
