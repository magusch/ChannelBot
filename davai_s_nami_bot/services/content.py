"""Post building (quick, synchronous) and generation (Celery tasks) for Django."""
from typing import List, Optional

from .. import celery_app as celery_module
from .. import crud
from ..city_context import use_city
from ..content_generator.models import (
    ContentGeneratorEventSelection,
    ContentGeneratorFilterSet,
)
from ..database.models import Events2Posts
from .city import resolve_city, rows_city
from .errors import InvalidArgument, NotFound

_TASK_PREFIX = "davai_s_nami_bot.celery_tasks."


def _send(city: str, name: str, *, args=None, kwargs=None) -> str:
    # before_task_publish stamps the current city on the message, so the task
    # runs as `city` without a city argument of its own.
    with use_city(city):
        task = celery_module.celery_app.send_task(_TASK_PREFIX + name, args=args, kwargs=kwargs)
    return task.id


# --- quick calls -----------------------------------------------------------


def make_post(event: dict, city: Optional[str] = None) -> dict:
    """Preview a post from event data: ``{post, place_id, main_category_id, price_int}``."""
    with use_city(resolve_city(city)):
        return crud.make_post_from_dict(event_data=event)


def bulk_create_posts(
    events: List[dict], save: bool = False, status: str = "ReadyToPost", city: Optional[str] = None
) -> List[dict]:
    """Build (and with ``save`` insert) many posts. An item's own ``city`` wins over
    ``city``; a failed item carries ``error`` and does not stop the others."""
    with use_city(resolve_city(city)):
        results = crud.bulk_make_and_save_posts(events_data=events, save=save, status=status)
        queue_embeddings(results)
        return results


def queue_embeddings(results: List[dict]) -> None:
    """Embed freshly saved events now rather than at the nightly run."""
    if any(r and r.get("saved") for r in results):
        celery_module.celery_app.send_task(
            _TASK_PREFIX + "embed_unembedded_events",
            kwargs={"table": "events2posts", "only_future": True},
        )


def remake_post(event_id: int, save: bool = False, city: Optional[str] = None) -> dict:
    with use_city(rows_city(Events2Posts, [event_id], city)):
        result = crud.remake_event_post(event_id=event_id, save=save)
    if not result:
        raise NotFound("Event not found")
    return result


# --- generation tasks: each returns a task id --------------------------------


def start_event_selection(filter_set_id: int, city: Optional[str] = None) -> str:
    target = rows_city(ContentGeneratorFilterSet, [filter_set_id], city)
    return _send(target, "content_generator_event_selection", args=[filter_set_id])


def start_generate_post(
    event_selection_id: int,
    post_template_id: int,
    generated_by_id: Optional[int] = None,
    city: Optional[str] = None,
) -> str:
    target = rows_city(ContentGeneratorEventSelection, [event_selection_id], city)
    return _send(
        target,
        "content_generator_generate_post",
        args=[event_selection_id, post_template_id, generated_by_id],
    )


def start_generate_post_ai(
    event_selection_id: Optional[int] = None,
    event_ids: Optional[List[int]] = None,
    post_template_id: Optional[int] = None,
    title: Optional[str] = None,
    city: Optional[str] = None,
) -> str:
    if not event_selection_id and not event_ids:
        raise InvalidArgument("event_selection_id or event_ids required")
    if event_selection_id:
        target = rows_city(ContentGeneratorEventSelection, [event_selection_id], city)
    else:
        target = rows_city(Events2Posts, event_ids, city)
    return _send(
        target,
        "content_generator_generate_post_ai",
        args=[event_selection_id, event_ids, post_template_id, title],
    )


def start_theme_post(
    filter_set_id: Optional[int] = None, dry_run: bool = False, city: Optional[str] = None
) -> str:
    """Draft only, no schedule row. Without ``filter_set_id`` -- theme rotation."""
    target = rows_city(ContentGeneratorFilterSet, [filter_set_id], city)
    return _send(
        target,
        "content_generator_theme_post",
        kwargs={"filter_set_id": filter_set_id, "dry_run": dry_run},
    )


def start_schedule_theme_post(
    filter_set_id: Optional[int] = None,
    days_ahead: Optional[int] = None,
    platform: str = "telegram",
    publish_hour: Optional[int] = None,
    publish_minute: Optional[int] = None,
    city: Optional[str] = None,
) -> str:
    """Planner: drafts + PostingSchedule rows for the next free slots."""
    target = rows_city(ContentGeneratorFilterSet, [filter_set_id], city)
    return _send(
        target,
        "schedule_theme_post",
        kwargs={
            "filter_set_id": filter_set_id,
            "days_ahead": days_ahead,
            "platform": platform or "telegram",
            "publish_hour": publish_hour,
            "publish_minute": publish_minute,
        },
    )
