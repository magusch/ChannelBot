import os
import json
import hashlib
import secrets
from datetime import datetime

from fastapi import HTTPException, Depends, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from sqlalchemy.orm import Session
from ..database.database_orm import get_db_session

from typing import Annotated

from ..celery_app import celery_app, redis_client
from ..city_context import current_city, is_city_set
from ..core.security import oauth2_scheme, decode_access_token
from .. import crud

from ..pydantic_models import UserOut


security = HTTPBearer()

API_TOKEN = os.environ.get('API_TOKEN', 'your-secure-api-token')


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    if token == API_TOKEN:
        return API_TOKEN
    else:
        raise HTTPException(status_code=403, detail="Invalid token")


def get_cache_key(params: dict):
    # The city is part of the key: the same filters give different events per city.
    key = json.dumps({"__city": current_city(), **params}, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()


def serialize_datetime(obj):
    """Serialize datetime to a string."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


async def log_api_request(request: Request, data=None):
    """
    Common function to log API requests
    Args:
        request: FastAPI request object
        data: Request data (can be None for empty requests)
    """
    if is_city_set() and (data is None or isinstance(data, dict)):
        # The city may come in the body, which the parsed model drops: log it.
        data = {**(data or {}), "city": current_city()}
    celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.log_api_request',
        args=[{
            'ip': request.client.host,
            'endpoint': str(request.url),
            'method': request.method,
            'status_code': 200,
            'timestamp': datetime.now().isoformat(),
            'user_agent': request.headers.get('User-Agent'),
            'request_data': json.dumps(data) if data is not None else None,
        }]
    )


def get_db():
    """Yield one SQLAlchemy session per request; commit/rollback/close live in get_db_session."""
    with get_db_session() as db:
        yield db

DbSession = Annotated[Session, Depends(get_db)]

def get_current_user(db: DbSession, token: str = Depends(oauth2_scheme)) -> UserOut:
    """Decode the token to get the current user."""
    nickname = decode_access_token(token)
    if not nickname:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = crud.get_user_by_nickname(db=db, nickname=nickname)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserOut.model_validate(user)


CurrentUser = Annotated[UserOut, Depends(get_current_user)]


def get_current_active_user(user: CurrentUser) -> UserOut:
    """Reject users deactivated after the token was issued."""
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user

ActiveCurrentUser = Annotated[UserOut, Depends(get_current_active_user)]

def verify_health_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Separate token for the health report only: a leaked monitoring token
    must not open the rest of the API. Unset token = endpoint closed, there is
    no fallback to API_TOKEN."""
    expected = os.environ.get('HEALTH_TOKEN')
    if not expected:
        raise HTTPException(status_code=503, detail="HEALTH_TOKEN is not configured")
    if not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid token")
    return credentials.credentials
