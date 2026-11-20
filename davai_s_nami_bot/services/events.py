"""Event listings, feed, single event and similar events."""
from typing import NamedTuple, Optional

from .. import crud
from ..city_context import use_city
from ..database.models import Events2Posts
from ..pydantic_models import EventFeedParameters, EventRequestParameters
from .cache import Cached, cache_key, cached_call, get_json, set_json
from .city import resolve_city, rows_city
from .errors import InvalidArgument, NotFound

SIMILAR_LIMIT_RANGE = (1, 50)


def list_events(params: EventRequestParameters, city: Optional[str] = None) -> Cached:
    """Filtered listing (REST /events/valid/): ``{events, total_count, request}``."""
    with use_city(resolve_city(city)):
        key = cache_key(params.model_dump(mode="json"))
        return cached_call(key, lambda: crud.get_events_by_date_and_category(params))


def event_feed(params: EventFeedParameters, city: Optional[str] = None) -> Cached:
    """Diverse feed (REST /events/feed/); ``request.diverse_total`` bounds paging."""
    with use_city(resolve_city(city)):
        key = cache_key(params.model_dump(mode="json"))
        return cached_call(
            key,
            lambda: crud.get_diverse_event_feed(
                params, per_category=params.per_category, per_day=params.per_day
            ),
        )


def get_valid_event(event_id: int, city: Optional[str] = None) -> Cached:
    """One publicly visible event (REST /events/valid/{id}).

    Returns the listing envelope; ``events`` is empty when the event does not
    exist or is not public -- the transport decides whether that is a 404.
    """
    with use_city(rows_city(Events2Posts, [event_id], city)):
        params = EventRequestParameters(ids=[event_id])
        return cached_call(
            f"event_{event_id}", lambda: crud.get_events_by_date_and_category(params)
        )


class SimilarOutcome(NamedTuple):
    result: dict  # {events, total_count, request}
    cached: bool
    # Set when the source event had no embedding: an embed task was queued and
    # the caller should wait for it, then ask again.
    pending_task_id: Optional[str] = None


def similar_events(event_id: int, limit: int = 10, city: Optional[str] = None) -> SimilarOutcome:
    """Nearest events by embedding (REST /events/{id}/similar)."""
    low, high = SIMILAR_LIMIT_RANGE
    if not low <= limit <= high:
        raise InvalidArgument(f"limit must be between {low} and {high}")

    with use_city(rows_city(Events2Posts, [event_id], city)):
        key = f"similar_events_{event_id}_{limit}"
        hit = get_json(key)
        if hit is not None:
            return SimilarOutcome(hit, True)

        result = crud.find_similar_events(event_id=event_id, limit=limit)
        if result is None:
            raise NotFound("Event not found")

        if result.get("request", {}).get("reason") == "no_embedding":
            from ..celery_tasks import embed_single_event

            task = embed_single_event.delay(event_id)
            return SimilarOutcome(result, False, task.id)

        set_json(key, result)
        return SimilarOutcome(result, False)
