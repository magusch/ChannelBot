"""City of an API request.

Two kinds of endpoints (the contract with Django, docs/multicity_api_and_timezones.md):

- **collection-scoped** (queue, feed, themes, scraping): the city comes with the
  request — ``?city=`` or a top-level ``"city"`` in a JSON body. ``CityMiddleware``
  enters it for the whole request, so the crud queries and every Celery task the
  endpoint queues run as that city. Missing → the default city (transition
  fallback, logged); ``all`` or an unknown code → 400.
- **object-scoped** (a list of ids): the city is the one of the rows. Use
  ``enter_city_of`` / ``city_of``: ids of several cities → 400, and a city sent
  with the request must match the rows.
"""
import json
import logging
from urllib.parse import parse_qs

from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool

from .. import city as city_module
from ..city_context import (
    SHARED_CITY,
    UnknownCity,
    current_city,
    is_city_set,
    reset_city,
    set_city,
    use_city,
)

log = logging.getLogger(__name__)

_BODY_METHODS = {"POST", "PUT", "PATCH"}


def _query_city(scope):
    values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("city")
    return values[0] if values else None


def _body_city(body: bytes):
    if not body:
        return None
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    value = data.get("city") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


async def _send_json(send, status_code, payload):
    body = json.dumps(payload).encode()
    await send({
        "type": "http.response.start",
        "status": status_code,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body})


class CityMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware): the contextvar it sets must reach the
    endpoint, and a JSON body read here has to be replayed to it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        code = _query_city(scope)
        downstream_receive = receive
        headers = dict(scope.get("headers") or [])
        content_type = headers.get(b"content-type", b"")
        is_json = not content_type or b"application/json" in content_type
        if code is None and scope.get("method") in _BODY_METHODS and is_json:
            chunks, more = [], True
            while more:
                message = await receive()
                chunks.append(message.get("body", b""))
                more = message.get("more_body", False)
            body = b"".join(chunks)
            code = _body_city(body)
            replayed = False

            async def replay_body():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            downstream_receive = replay_body

        if code is None:
            return await self.app(scope, downstream_receive, send)

        try:
            code = await run_in_threadpool(city_module.validate_city, code)
        except UnknownCity as e:
            return await _send_json(send, status.HTTP_400_BAD_REQUEST, {"detail": str(e)})

        token = set_city(code)
        try:
            await self.app(scope, downstream_receive, send)
        finally:
            reset_city(token)


def _resolve_rows_city(model, ids, id_column="id"):
    explicit = current_city() if is_city_set() else None
    try:
        city = city_module.city_of_ids(model, ids, id_column=id_column)
    except city_module.MixedCities as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if city == SHARED_CITY:
        return None
    if city and explicit and city != explicit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"rows belong to city {city!r}, request says {explicit!r}",
        )
    return city


def city_of(model, ids, id_column="id"):
    """City for an object-scoped call from sync code: the rows' city, or the
    current one when no row matched (the endpoint then reports "not found")."""
    return _resolve_rows_city(model, ids, id_column) or current_city()


async def enter_city_of(model, ids, id_column="id"):
    """Enter the rows' city for the rest of an async endpoint.

    The contextvar is set in the request's own task, so everything the endpoint
    does afterwards — crud calls, ``send_task`` headers — runs as that city. It is
    restored when the request ends (CityMiddleware / the task finishing).
    """
    city = await run_in_threadpool(_resolve_rows_city, model, ids, id_column)
    if city and city != current_city():
        set_city(city)
    return current_city()


def send_task_per_city(celery_app, name, **options):
    """Queue ``name`` for the request's city, or for every scheduled city when
    the request named none.

    For refreshes of shared data: a prompt with ``city_id='all'`` edited in
    Django changes every city's merged parameters, not only the default one's.
    Returns the first task (its id is what the caller reports).
    """
    from ..settings.settings_loader import settings

    codes = [current_city()] if is_city_set() else settings.scheduled_cities()
    tasks = []
    for code in codes:
        with use_city(code):
            tasks.append(celery_app.send_task(name, **options))
    return tasks[0]


__all__ = [
    "CityMiddleware", "city_of", "enter_city_of", "send_task_per_city", "use_city",
]
