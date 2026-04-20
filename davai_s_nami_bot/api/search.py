from fastapi import APIRouter, Depends, Request

from .. import crud
from .dependencies import verify_token, log_api_request

router = APIRouter(
    prefix="/search",
    tags=["Search"],
    dependencies=[Depends(verify_token)],
)


@router.get("/",
             summary="Поиск событий и мест",
             description="Полнотекстовый поиск. Параметр `type`: `event` (по умолчанию), `place`, или любое другое значение для поиска и по событиям, и по местам.")
async def search(query: str, limit: int = 10, type: str = 'event', request: Request = None):
    events, places = [], []
    if type == 'event':
        events = crud.search_events_by_string(query, limit)
    elif type == 'place':
        places = crud.search_places_by_name(query, limit)
    else:
        events = crud.search_events_by_string(query, limit)
        places = crud.search_places_by_name(query, limit)
    await log_api_request(request, {'query': query, 'limit': limit, 'type': type})
    return {"events": events, "places": places}
