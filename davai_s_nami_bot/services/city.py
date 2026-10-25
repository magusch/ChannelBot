"""City resolution for service calls.

Collection-scoped calls (feed, search, themes) run in the requested city.
Object-scoped calls (an event id, a selection id) run in the city of the rows,
and a requested city that disagrees with them is an error -- the same contract
as ``api/city.py``, minus HTTP.
"""
from typing import Iterable, Optional

from .. import city as city_module
from ..city_context import SHARED_CITY, UnknownCity, current_city
from .errors import InvalidArgument


def resolve_city(code: Optional[str]) -> str:
    """Validated city code; empty means the current (or default) city."""
    if not code:
        return current_city()
    try:
        return city_module.validate_city(code)
    except UnknownCity as e:
        raise InvalidArgument(str(e)) from e


def rows_city(model, ids: Iterable, requested: Optional[str] = None) -> str:
    """City of ``model`` rows with ``ids``.

    No matching row, or shared rows (``city_id='all'``, e.g. a common theme),
    keep the requested city; the caller then reports "not found" itself.
    """
    requested_city = resolve_city(requested)
    try:
        city = city_module.city_of_ids(model, list(ids))
    except city_module.MixedCities as e:
        raise InvalidArgument(str(e)) from e
    if not city or city == SHARED_CITY:
        return requested_city
    if requested and city != requested_city:
        raise InvalidArgument(f"rows belong to city {city!r}, request says {requested_city!r}")
    return city
