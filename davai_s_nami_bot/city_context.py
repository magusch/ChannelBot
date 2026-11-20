"""The current city of a request, task or thread.

Dependency-free on purpose: settings, the ORM hooks and Celery signals all read it,
so it must not import any of them.

A city is a ``city_city.code`` (``spb``, ``kzn``). ``all`` is not a city: it marks
shared rows (prompts, themes) and is never a target.
"""
import contextvars
import os
from contextlib import contextmanager

DEFAULT_CITY = os.environ.get("DSN_DEFAULT_CITY", "spb")
SHARED_CITY = "all"

_current_city = contextvars.ContextVar("dsn_city", default=None)


class UnknownCity(ValueError):
    """Raised for a code that is not a real city (missing, ``all`` or unknown)."""


def current_city() -> str:
    """The city of the running code; the default city when none was set."""
    return _current_city.get() or DEFAULT_CITY


def is_city_set() -> bool:
    """True when the caller entered a city explicitly (not the fallback)."""
    return _current_city.get() is not None


def normalize_city(code) -> str:
    """Lower-cased, stripped code; raises UnknownCity for empty or ``all``."""
    value = str(code or "").strip().lower()
    if not value or value == SHARED_CITY:
        raise UnknownCity(f"not a city: {code!r}")
    return value


def set_city(code):
    """Enter ``code`` without a context manager; returns the reset token."""
    return _current_city.set(normalize_city(code))


def reset_city(token) -> None:
    _current_city.reset(token)


@contextmanager
def use_city(code):
    """Run the block as city ``code``. ``None`` keeps the current city."""
    if code is None:
        yield current_city()
        return
    token = set_city(code)
    try:
        yield current_city()
    finally:
        _current_city.reset(token)


def run_in_context(func):
    """Wrap ``func`` so it runs with the caller's contextvars (city included).

    ``ThreadPoolExecutor.submit`` does not copy contextvars: without this a scraper
    run in a worker thread would silently fall back to the default city.
    """
    ctx = contextvars.copy_context()

    def wrapper(*args, **kwargs):
        return ctx.run(func, *args, **kwargs)

    return wrapper
