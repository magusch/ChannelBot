import os, json
from datetime import datetime, timedelta

from passlib.context import CryptContext
from typing import Any, Dict
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer

import hmac
import hashlib
import urllib.parse

SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
BOT_TOKEN = os.environ['BOT_TOKEN']
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
        subject: str, expires_delta: timedelta = None
) -> str:
    """Generate a JWT token for the given subject (user identifier)."""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    # Payload - data contained in the token
    to_encode = {"exp": expire, "sub": str(subject)}

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(subject: str) -> str:
    """Generate long-live Refresh Token."""
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {"exp": expire, "sub": str(subject)}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Any:
    """Decode a JWT token and return the subject (user identifier)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        return None


def check_telegram_auth_data(init_data: str) -> Dict[str, Any]:
    """
    Checks the integrity of Telegram WebApp data.
    If the check is successful, returns the decoded user data.
    Otherwise, raises an exception.
    """
    if not BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is not set.")

    # Split the init_data into key-value pairs
    partially_decoded = urllib.parse.unquote(init_data)
    params = urllib.parse.parse_qs(partially_decoded)

    if 'hash' not in params:
        raise ValueError("Hash parameter is missing in initData.")

    received_hash = params.pop('hash')[0]
    data_check_string = []

    # Sort the keys to ensure consistent ordering (telegram requirement)
    for key in sorted(params.keys()):
        if key != 'hash':
            data_check_string.append(f"{key}={params[key][0]}")
    data_check_string = '\n'.join(data_check_string)

    # Making secret_key where WebAppData is the key and BOT_TOKEN is the message
    secret_key = hmac.new(
        "WebAppData".encode('utf-8'),
        BOT_TOKEN.encode('utf-8'),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    if calculated_hash != received_hash:
        return None

    user_data = json.loads(params.get('user', [None])[0])
    return user_data

