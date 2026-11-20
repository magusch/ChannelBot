"""Keyword and semantic search."""
from typing import List, Optional, Union

from .. import celery_app as celery_module
from .. import crud
from ..city_context import use_city
from .city import resolve_city
from .errors import InvalidArgument

KEYWORD_TARGETS = ("event", "place", "all")
SEMANTIC_LIMIT_RANGE = (1, 50)


def keyword_search(
    query: str, target: str = "event", limit: int = 10, city: Optional[str] = None
) -> dict:
    """REST GET /search/: ``{events, places}``.

    ``target`` is ``event``, ``place`` or ``all``; REST also treats any unknown
    value as ``all``, which is kept there and not repeated here.
    """
    if target not in KEYWORD_TARGETS:
        raise InvalidArgument(f"target must be one of {KEYWORD_TARGETS}")
    events, places = [], []
    with use_city(resolve_city(city)):
        if target != "place":
            events = crud.search_events_by_string(query, limit)
        if target != "event":
            places = crud.search_places_by_name(query, limit)
    return {"events": events, "places": places}


def start_semantic_search(
    message: str,
    limit: int = 5,
    max_distance: Optional[float] = None,
    history: Optional[List[Union[str, dict]]] = None,
    city: Optional[str] = None,
) -> str:
    """Queue the NL search task; returns its id (wait with ``tasks.watch_task``)."""
    low, high = SEMANTIC_LIMIT_RANGE
    if not low <= limit <= high:
        raise InvalidArgument(f"limit must be between {low} and {high}")
    # The task runs as the city that is current at publish time.
    with use_city(resolve_city(city)):
        task = celery_module.celery_app.send_task(
            "davai_s_nami_bot.celery_tasks.semantic_event_search",
            kwargs={
                "message": message,
                "limit": limit,
                "max_distance": max_distance,
                "history": history,
            },
        )
    return task.id
