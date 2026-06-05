import os
import json
import hashlib
from datetime import datetime

from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ..celery_app import celery_app, redis_client

security = HTTPBearer()

API_TOKEN = os.environ.get('API_TOKEN', 'your-secure-api-token')


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    if token == API_TOKEN:
        return API_TOKEN
    else:
        raise HTTPException(status_code=403, detail="Invalid token")


def get_cache_key(params: dict):
    key = json.dumps(params, sort_keys=True)
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
