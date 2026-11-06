from typing import List

from fastapi import APIRouter, Request
from fastapi import HTTPException, status

from .dependencies import ActiveCurrentUser
from .request_log import track_request

from ..pydantic_models import EventOut, FavouriteOut
from .. import crud
from ..database.models import Events2Posts
from .city import city_of, use_city

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

@router.post("/me/events/{event_id}", response_model=FavouriteOut, status_code=status.HTTP_201_CREATED)
def add_event_to_favourites(
        event_id: int,
        user: ActiveCurrentUser,
        request: Request,
):
    """Adds an event to the user's favourites."""
    track_request(request, {"event_id": event_id}, auth_user_id=user.id)

    with use_city(city_of(Events2Posts, [event_id])):
        success = crud.add_event_to_user(user_id=user.id, event_id=event_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add event to favourites"
        )

    return {"detail": "Event added to favourites", "type": "event", "id": event_id}


@router.delete("/me/events/{event_id}", response_model=FavouriteOut)
def remove_event_from_favourites(
        event_id: int,
        user: ActiveCurrentUser,
        request: Request,
):
    """Removes an event from the user's favourites."""
    track_request(request, {"event_id": event_id}, auth_user_id=user.id)

    with use_city(city_of(Events2Posts, [event_id])):
        success = crud.remove_event_from_user(user_id=user.id, event_id=event_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to remove event from favourites"
        )

    return {"detail": "Event removed from favourites", "type": "event", "id": event_id}


@router.get("/me/events", response_model=List[EventOut])
def get_favourite_events(
        user: ActiveCurrentUser,
        request: Request,
):
    """Retrieves the user's favourite events."""
    track_request(request, auth_user_id=user.id)

    events = crud.get_user_favourite_events(user_id=user.id)

    return events
