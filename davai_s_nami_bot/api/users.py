from typing import List

from fastapi import APIRouter

from fastapi import HTTPException, status, Depends

from ..core.security import oauth2_scheme, decode_access_token
from ..pydantic_models import EventOut, FavouriteOut
from .. import crud

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


def get_current_user(token: str = Depends(oauth2_scheme)):
    """Decode the token to get the current user."""
    nickname = decode_access_token(token)
    if not nickname:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = crud.get_user_by_nickname(nickname=nickname)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.post("/me/events/{event_id}", response_model=FavouriteOut, status_code=status.HTTP_201_CREATED)
def add_event_to_favourites(
        event_id: int,
        token: str = Depends(oauth2_scheme)
):
    """Adds an event to the user's favourites."""

    user = get_current_user(token)

    success = crud.add_event_to_user(user_id=user["id"], event_id=event_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to add event to favourites"
        )

    return {"detail": "Event added to favourites", "type": "event", "id": event_id}


@router.delete("/me/events/{event_id}", response_model=FavouriteOut)
def remove_event_from_favourites(
        event_id: int,
        token: str = Depends(oauth2_scheme)
):
    """Removes an event from the user's favourites."""

    user = get_current_user(token)

    success = crud.remove_event_from_user(user_id=user['id'], event_id=event_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to remove event from favourites"
        )

    return {"detail": "Event removed from favourites", "type": "event", "id": event_id}


@router.get("/me/events", response_model=List[EventOut])
def get_favourite_events(
        token: str = Depends(oauth2_scheme)
):
    """Retrieves the user's favourite events."""

    user = get_current_user(token)

    events = crud.get_user_favourite_events(user_id=user['id'])

    return events
