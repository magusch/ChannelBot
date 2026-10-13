"""Cities: ``city_city`` rows (Django-owned) plus helpers around the current city.

What lives where:
- the current city — ``city_context`` (contextvar, no dependencies);
- identity, name forms, channels — ``city_city`` (read here, cached briefly);
- secrets — env, shared by all cities;
- behaviour (scrapers, thresholds) — ``settings.json`` (``cities.<code>`` overlay).
"""
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from . import city_context
from .city_context import (
    SHARED_CITY,
    UnknownCity,
    current_city,
    normalize_city,
    use_city,
)

log = logging.getLogger(__name__)

_CACHE_TTL = 300
_cache: Dict[str, "CityInfo"] = {}
_cache_at = 0.0
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class CityInfo:
    code: str
    name: str
    name_gen: str
    name_loc: str
    timezone: str
    is_active: bool
    channel_id: Optional[str] = None
    dev_channel_id: Optional[str] = None
    channel_link: Optional[str] = None
    vk_group_id: Optional[str] = None
    vk_dev_group_id: Optional[str] = None
    bot_url: Optional[str] = None
    dgis_slug: Optional[str] = None


def _strip_preposition(value: str) -> str:
    """``"в Казани"`` → ``"Казани"``: ``city_city.name_loc`` carries the preposition,
    while prompts here already say «о мероприятиях в {city_name_loc}»."""
    value = (value or "").strip()
    for prefix in ("во ", "в "):
        if value.lower().startswith(prefix):
            return value[len(prefix):].strip()
    return value


def _str_or_none(value) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _load_cities() -> Dict[str, CityInfo]:
    from .database.database_orm import get_db_session
    from .database.models import City

    with get_db_session() as db:
        rows = db.query(City).execution_options(all_cities=True).all()
        return {
            row.code: CityInfo(
                code=row.code,
                name=row.name,
                name_gen=row.name_gen,
                name_loc=_strip_preposition(row.name_loc),
                timezone=row.timezone or "Europe/Moscow",
                is_active=bool(row.is_active),
                channel_id=_str_or_none(row.channel_id),
                dev_channel_id=_str_or_none(row.dev_channel_id),
                channel_link=_str_or_none(row.channel_link),
                vk_group_id=_str_or_none(row.vk_group_id),
                vk_dev_group_id=_str_or_none(row.vk_dev_group_id),
                bot_url=_str_or_none(row.bot_url),
                dgis_slug=_str_or_none(row.dgis_slug),
            )
            for row in rows
            if row.code != SHARED_CITY
        }


def all_cities(refresh: bool = False) -> Dict[str, CityInfo]:
    """Every real city by code (``all`` excluded). Cached for ``_CACHE_TTL``.

    A failed read keeps serving the previous copy; with nothing cached it returns
    ``{}`` and callers fall back to their defaults.
    """
    global _cache, _cache_at
    with _cache_lock:
        if not refresh and _cache and time.time() - _cache_at < _CACHE_TTL:
            return _cache
        try:
            _cache = _load_cities()
            _cache_at = time.time()
        except Exception as e:  # noqa: BLE001 — city_city unreachable/missing
            log.warning(f"city: could not read city_city, using cached copy: {e}")
            _cache_at = time.time()
        return _cache


def get_city(code: Optional[str] = None) -> Optional[CityInfo]:
    return all_cities().get(code or current_city())


def city_name_forms(code: Optional[str] = None) -> Optional[dict]:
    info = get_city(code)
    if not info or not info.name:
        return None
    return {
        "nom": info.name,
        "gen": info.name_gen or info.name,
        "loc": info.name_loc or info.name,
    }


def validate_city(code) -> str:
    """Normalized code of a real city; raises UnknownCity otherwise.

    When ``city_city`` cannot be read, the default city and the cities configured
    in settings are accepted, so a DB hiccup does not turn into 400s for SPb.
    """
    value = normalize_city(code)
    known = all_cities()
    if known:
        if value not in known:
            raise UnknownCity(f"unknown city: {code!r}")
        return value
    from .settings.settings_loader import settings

    if value == city_context.DEFAULT_CITY or value in settings.cities_config:
        return value
    raise UnknownCity(f"unknown city: {code!r}")


# --- channel destinations ---------------------------------------------------

_ENV_FALLBACK = {
    "channel_id": "CHANNEL_ID",
    "dev_channel_id": "DEV_CHANNEL_ID",
    "channel_link": "CHANNEL_LINK",
    "vk_group_id": "VK_GROUP_ID",
    "vk_dev_group_id": "VK_DEV_GROUP_ID",
}


def city_value(field: str, code: Optional[str] = None) -> Optional[str]:
    """A ``city_city`` column of the city, with the env fallback for the default
    city only (see module docstring)."""
    code = code or current_city()
    info = get_city(code)
    value = getattr(info, field, None) if info else None
    if value:
        return value
    env_name = _ENV_FALLBACK.get(field)
    if env_name and code == city_context.DEFAULT_CITY:
        return _str_or_none(os.environ.get(env_name))
    return None


def channel_destinations(platform: str, code: Optional[str] = None) -> dict:
    """``{"prod": {"destination_id": ...}, "dev": {...}}`` — the shape the clients'
    ``constants`` always had."""
    if platform == "vk":
        prod, dev = "vk_group_id", "vk_dev_group_id"
    else:
        prod, dev = "channel_id", "dev_channel_id"
    return {
        "prod": {"destination_id": city_value(prod, code)},
        "dev": {"destination_id": city_value(dev, code)},
    }


# --- object-scoped helpers -------------------------------------------------


class MixedCities(ValueError):
    """Ids of one request belong to more than one city."""


def city_of_ids(model, ids: Iterable, id_column: str = "id") -> Optional[str]:
    """The single city of ``model`` rows with these ids.

    Reads across cities (the caller does not know the city yet). Returns None
    when no row matched; raises MixedCities when the rows span several cities.
    """
    ids = [i for i in ids if i is not None]
    if not ids:
        return None
    from .database.database_orm import get_db_session

    column = getattr(model, id_column)
    with get_db_session() as db:
        rows = (
            db.query(model.city_id)
            .filter(column.in_(ids))
            .distinct()
            .execution_options(all_cities=True)
            .all()
        )
    codes = sorted({row[0] for row in rows if row[0]})
    if len(codes) > 1:
        raise MixedCities(f"ids span several cities: {codes}")
    return codes[0] if codes else None


def run_for_city(code, func, *args, **kwargs):
    """``func(*args, **kwargs)`` as city ``code`` (validated)."""
    with use_city(validate_city(code)):
        return func(*args, **kwargs)


# --- Redis keys ------------------------------------------------------------


def city_key(name: str, code: Optional[str] = None) -> str:
    """Per-city Redis key: ``<city>:<name>``."""
    return f"{code or current_city()}:{name}"


def legacy_keys(name: str, code: Optional[str] = None) -> list:
    """Pre-multicity key names still holding the default city's state.

    Only the default city ever wrote unprefixed keys, so only it reads them back.
    """
    code = code or current_city()
    return [name] if code == city_context.DEFAULT_CITY else []


def migrate_legacy_key(redis_client, name: str, code: Optional[str] = None) -> str:
    """Move the default city's unprefixed key to its per-city name, once.

    For live state such as the scheduled posting task: a scheduler that started
    from an empty per-city key would queue a second post next to the one the
    old key still points to. RENAMENX keeps it atomic and never overwrites a
    per-city key written meanwhile. Returns the per-city key.
    """
    key = city_key(name, code)
    for legacy in legacy_keys(name, code):
        try:
            if redis_client.exists(legacy):
                redis_client.renamenx(legacy, key)
        except Exception as e:  # noqa: BLE001 — a Redis hiccup must not stop posting
            log.warning(f"city: could not migrate Redis key {legacy!r} → {key!r}: {e}")
    return key


def get_with_legacy(redis_client, name: str, code: Optional[str] = None):
    """GET the per-city key, falling back to the default city's legacy key."""
    value = redis_client.get(city_key(name, code))
    if value is not None:
        return value
    for legacy in legacy_keys(name, code):
        value = redis_client.get(legacy)
        if value is not None:
            return value
    return None
