import json

from fastapi import APIRouter, Request, Depends
from fastapi import HTTPException, status

from ..pydantic_models import EventOut, EventRequestParameters
from ..celery_app import redis_client
from .. import crud
from .dependencies import verify_token, get_cache_key, serialize_datetime, log_api_request

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
