from fastapi import APIRouter

from fastapi import HTTPException, status

from ..pydantic_models import UserCreate, UserOut
from .. import crud

router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(
        user_data: UserCreate
):
    new_user = crud.register_user(user_data)
    if not new_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User exists. Email is not unique"
        )
    return new_user

@router.post("/login")
def login_user(credentials: dict):
    # login logic goes here
    ...