"""api_request_log for user-facing endpoints: who asked, what, and how it ended."""

import json
import logging
from datetime import datetime

from fastapi import Request

from ..celery_app import celery_app
from ..city_context import current_city, is_city_set

log = logging.getLogger(__name__)

CLIENT_CONTEXT_HEADER = "x-client-context"
MAX_CLIENT_CONTEXT_BYTES = 2048
_STATE_KEY = "api_log"


def parse_client_context(raw):
    """Client-declared context from the header: a JSON object, else a marker."""
    if not raw:
        return None
    if len(raw.encode("utf-8", errors="replace")) > MAX_CLIENT_CONTEXT_BYTES:
        return {"invalid": "too_long"}
    try:
        value = json.loads(raw)
    except ValueError:
        return {"invalid": "not_json"}
    if not isinstance(value, dict):
        return {"invalid": "not_object"}
    return value


def _header(request: Request, name: str):
    for key, value in request.scope.get("headers") or []:
        if key.decode("latin-1").lower() == name:
            return value.decode("utf-8", errors="replace")
    return None


def client_context(request: Request, auth_user_id=None):
    """Header context plus what the server knows itself (proxy chain, JWT user)."""
    context = dict(parse_client_context(_header(request, CLIENT_CONTEXT_HEADER)) or {})
    forwarded = _header(request, "x-forwarded-for")
    if forwarded:
        context["forwarded_for"] = forwarded
    if auth_user_id is not None:
        context["auth_user_id"] = auth_user_id
    return context or None


def track_request(request: Request, data=None, *, auth_user_id=None):
    """Mark the request for logging; RequestLogMiddleware writes it after the response."""
    if is_city_set() and (data is None or isinstance(data, dict)):
        # The city may come in the body, which the parsed model drops: log it.
        data = {**(data or {}), "city": current_city()}
    request.state.api_log = {
        "ip": request.client.host if request.client else "",
        "endpoint": str(request.url),
        "method": request.method,
        "timestamp": datetime.now().isoformat(),
        "user_agent": request.headers.get("User-Agent"),
        "request_data": json.dumps(data) if data is not None else None,
        "client": client_context(request, auth_user_id),
    }


async def log_api_request(request: Request, data=None, *, auth_user_id=None):
    """Async alias of track_request for existing call sites."""
    track_request(request, data, auth_user_id=auth_user_id)


def send_request_log(entry: dict, status_code: int):
    try:
        celery_app.send_task(
            "davai_s_nami_bot.celery_tasks.log_api_request",
            args=[{**entry, "status_code": status_code}],
        )
    except Exception:
        log.exception("api_request_log: failed to queue %s", entry.get("endpoint"))


class RequestLogMiddleware:
    """Pure ASGI: writes the entry a handler left in request.state, with the real status."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        state = scope.setdefault("state", {})
        status_code = 500

        async def send_with_status(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            entry = state.pop(_STATE_KEY, None)
            if entry:
                send_request_log(entry, status_code)
