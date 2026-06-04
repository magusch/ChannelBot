import json

from fastapi import APIRouter, Request, Depends, Response
from fastapi import HTTPException, status

from ..pydantic_models import EventOut, EventRequestParameters
from ..celery_app import redis_client
from .. import crud
from .dependencies import verify_token, get_cache_key, serialize_datetime, log_api_request
from .schemas import BulkCreatePostRequest, SimilarEventsResponse

router = APIRouter(
    prefix="/events",
    tags=["Events"]
)


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int):
    """Retrieve event details by event ID."""
    event = crud.get_event_by_id(event_id=event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    return event


@router.post("/valid/", dependencies=[Depends(verify_token)],
              summary="List events by filters",
              description="Retrieve events with filters: date, category, place, price, status. Cached for 10 min.")
async def get_valid_events(body: EventRequestParameters, request: Request):
    data = body.model_dump(mode='json')
    cache_key = get_cache_key(data)
    cached_data = redis_client.get(cache_key)

    await log_api_request(request, data)

    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    params = body.with_defaults()

    result = crud.get_events_by_date_and_category(params)
    redis_client.setex(cache_key, 60 * 10, json.dumps(result, default=serialize_datetime))
    return {"status": "success", "result": result}


@router.post("/make_post/", dependencies=[Depends(verify_token)],
              summary="Generate a post from data",
              description="Accepts a dict with event data, returns a ready-made post. Does not save to DB.")
def make_post(event: dict):
    result = crud.make_post_from_dict(event_data=event)
    return {"status": "success", "result": result}


@router.post("/bulk_create_post/", dependencies=[Depends(verify_token)],
              summary="Bulk generate posts (+ optional save)",
              description="Bulk variant of /make_post. Body: {events: [...], save: bool, status?: str}. "
                          "Per-event: resolves place, generates markdown, resolves category, parses price. "
                          "save=true also inserts rows into Events2Posts. Per-event errors do not abort the batch.")
def bulk_create_post(body: BulkCreatePostRequest):
    results = crud.bulk_make_and_save_posts(
        events_data=body.events,
        save=body.save,
        status=body.status,
    )
    return {"status": "success", "result": results, "count": len(results)}


@router.post("/remake_post/{event_id}", dependencies=[Depends(verify_token)],
              summary="Regenerate event post",
              description="Generates a new post text. save=false — preview only, save=true — saves to DB.")
def remake_post(event_id: int, save: bool = False):
    result = crud.remake_event_post(event_id=event_id, save=save)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    return {"status": "success", "result": result}


@router.get("/{event_id}/similar",
            response_model=SimilarEventsResponse,
            dependencies=[Depends(verify_token)],
            summary="Find similar events by embedding",
            description="Returns events whose embedding is closest (cosine distance) "
                        "to the given event among publicly-valid Events2Posts. "
                        "Source event is excluded. Only events embedded by the same "
                        "model are compared. Cached for 10 min.\n\n"
                        "If the source event has no embedding yet, dispatches a Celery "
                        "embed task and returns 202 with {status: 'pending', task_id}. "
                        "Client should poll /tasks/status/{task_id} then re-request.")
async def get_similar_events(event_id: int, request: Request, limit: int = 10):
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 50",
        )

    cache_key = f"similar_events_{event_id}_{limit}"
    cached_data = redis_client.get(cache_key)
    await log_api_request(request, {"event_id": event_id, "limit": limit})

    if cached_data:
        return {"status": "success", "message": "cached", "result": json.loads(cached_data)}

    result = crud.find_similar_events(event_id=event_id, limit=limit)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    # Source has no embedding yet — dispatch a Celery embed task and tell the client to retry.
    if result.get('request', {}).get('reason') == 'no_embedding':
        from ..celery_tasks import embed_single_event
        task = embed_single_event.delay(event_id)
        return Response(
            status_code=status.HTTP_202_ACCEPTED,
            content=json.dumps({
                "status": "pending",
                "task_id": task.id,
                "result": result,
                "message": "Source event has no embedding; embedding task dispatched. "
                           "Poll /tasks/status/{task_id} then retry this endpoint.",
            }, default=serialize_datetime),
            media_type="application/json",
        )

    redis_client.setex(cache_key, 60 * 10, json.dumps(result, default=serialize_datetime))
    return {"status": "success", "result": result}


@router.post("/valid/{event_id}", dependencies=[Depends(verify_token)],
              summary="Event by ID (cached)",
              description="Retrieve an event by ID. Cached for 10 min.")
async def get_valid_event_by_id(event_id: int, request: Request):
    await log_api_request(request, {"ids": [event_id]})

    cached_data = redis_client.get(f"event_{event_id}")
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    data = {"ids": [event_id]}

    params = EventRequestParameters(**data).with_defaults()
    result = crud.get_events_by_date_and_category(params)
    redis_client.setex(f"event_{event_id}", 60 * 10, json.dumps(result, default=serialize_datetime))

    return {"status": "success", "result": result}
