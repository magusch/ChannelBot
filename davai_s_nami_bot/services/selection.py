"""A digest's event pool, as the bot shows it behind the post's link."""
import json
from typing import Optional

from ..city_context import use_city
from ..content_generator import crud as cg_crud
from ..content_generator.models import ContentGeneratorEventSelection
from .cache import Cached, get_json, set_json
from .city import rows_city
from .errors import InvalidArgument, NotFound

SELECTION_LIMIT_RANGE = (1, 200)


def _generation_settings(selection: dict) -> dict:
    raw = selection.get("generation_settings")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (json.JSONDecodeError, TypeError):
        return {}


def get_selection(selection_id: int, limit: int = 50, city: Optional[str] = None) -> Cached:
    """REST GET /content-generator/selection/{id}/:
    ``{events, total_count, selection: {id, name, shown_ids, dropped}}``."""
    low, high = SELECTION_LIMIT_RANGE
    if not low <= limit <= high:
        raise InvalidArgument(f"limit must be between {low} and {high}")

    with use_city(rows_city(ContentGeneratorEventSelection, [selection_id], city)):
        key = f"cg_selection_{selection_id}_{limit}"
        hit = get_json(key)
        if hit is not None:
            return Cached(hit, True)

        selection = cg_crud.get_event_selection(selection_id)
        if not selection:
            raise NotFound("Event selection not found")

        found = cg_crud.get_selection_events(selection_id, limit=limit)
        result = {
            "events": found["events"],
            "total_count": found["total_count"],
            "selection": {
                "id": selection["id"],
                "name": selection["name"],
                "shown_ids": _generation_settings(selection).get("shown_ids") or [],
                # Stored events that are no longer showable.
                "dropped": found["dropped"],
            },
        }
        set_json(key, result)
        return Cached(result, False)
