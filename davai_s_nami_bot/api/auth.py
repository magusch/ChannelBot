from fastapi import APIRouter, Response, Cookie

from fastapi import HTTPException, status, Depends

from ..core.security import create_access_token, create_refresh_token_cookie, oauth2_scheme, decode_access_token,\
    check_telegram_auth_data
from ..pydantic_models import UserCreate, UserOut, Token, UserLogin, UserUpdate, TelegramLoginData
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


@router.post("/login", response_model=Token)
def login_user(user_data: UserLogin, response: Response):
    user = crud.authenticate_user(
        nickname=user_data.nickname,
        password=user_data.password
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect nickname or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    access_token = create_access_token(subject=user["nickname"])
    refresh_token_cookie = create_refresh_token_cookie(subject=user["nickname"])

    response.set_cookie(**refresh_token_cookie)

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=Token)
def refresh_access_token(
        response: Response,
        refresh_token: str = Cookie(None, alias="refresh_token"),
):
    """Refreshes the access token using the provided refresh token."""

    if not refresh_token:
        # May be 401 if the user is not authorized
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found in cookies"
        )

    try:
        nickname = decode_access_token(refresh_token)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    user = crud.get_user_by_nickname(nickname)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    new_access_token = create_access_token(subject=user["nickname"])
    refresh_token_cookie = create_refresh_token_cookie(subject=user["nickname"])
    response.set_cookie(**refresh_token_cookie)

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserOut)
def read_users_me(token: str = Depends(oauth2_scheme)):
    """Return the current authorized user information"""

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    nickname = decode_access_token(token)
    if nickname is None:
        raise credentials_exception

    current_user = crud.get_user_by_nickname(nickname=nickname)
    return current_user


@router.put("/me", response_model=UserOut)
def update_user(
    user_update: UserUpdate,
    token: str = Depends(oauth2_scheme)
):
    """Updates the current authorized user's information"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    nickname = decode_access_token(token)
    if nickname is None:
        raise credentials_exception
    updated_user = crud.update_user(nickname=nickname, user_update=user_update)
    return updated_user


@router.post("/telegram/login", response_model=Token)
def telegram_login(
        login_data: TelegramLoginData, response: Response,
):
    """
    Checks Telegram login data, creates or retrieves the user,
    """

    telegram_user_info = check_telegram_auth_data(login_data.init_data)
    if not telegram_user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram data hash mismatch. Data integrity compromised."
        )

    telegram_id = telegram_user_info['id']
    user = crud.get_or_create_user_by_telegram_id(telegram_id, telegram_user_info)

    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    subject = user["nickname"] if user["nickname"] else str(user["telegram_id"])

    access_token = create_access_token(subject=subject)
    refresh_token_cookie = create_refresh_token_cookie(subject=subject)
    response.set_cookie(**refresh_token_cookie)

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }
