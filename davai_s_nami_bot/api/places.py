import json

from fastapi import APIRouter, Depends, Request

from ..pydantic_models import PlaceRequestParameters
from ..celery_app import redis_client
from .. import crud
from .dependencies import verify_token, get_cache_key, serialize_datetime, log_api_request

router = APIRouter(
    prefix="/places",
    tags=["Places"],
    dependencies=[Depends(verify_token)],
)


@router.post("/",
              summary="List places",
              description="Retrieve places with metro filtering and pagination. Cached for 10 min.")
async def get_places(body: PlaceRequestParameters, request: Request):
    data = body.model_dump(mode='json')
    await log_api_request(request, data)
    cache_key = get_cache_key(data)
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    places = crud.get_places(body)
    redis_client.setex(cache_key, 60 * 10, json.dumps(places, default=serialize_datetime))
    return {
        "status": "success",
        "result": {
            'request': data,
            'places': places
        }
    }


@router.post("/{place_id}",
              summary="Place by ID",
              description="Retrieve a place by ID. Cached for 10 min.")
async def get_place_by_id(place_id: int, request: Request):
    await log_api_request(request, {'place_id': place_id})
    cached_data = redis_client.get(f"place_{place_id}")
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    data = {"ids": [place_id]}

    params = PlaceRequestParameters(**data)
    places = crud.get_places(params)
    redis_client.setex(f"place_{place_id}", 60 * 10, json.dumps(places, default=serialize_datetime))
    return {
        "status": "success",
        "result": {
            'request': data,
            'places': places
        }
    }
