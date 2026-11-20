"""Geocoding interface and shared request quota."""

import re
import os
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Optional, Protocol
from uuid import uuid4


class GeocodingError(Exception):
    """A geocoding request could not be completed."""


class GeocodingLimitError(GeocodingError):
    """The local or provider quota has been reached."""


@dataclass(frozen=True)
class GeoResult:
    latitude: float
    longitude: float
    formatted_address: str
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    street: Optional[str] = None
    house_number: Optional[str] = None
    result_type: Optional[str] = None
    confidence: Optional[float] = None
    city_confidence: Optional[float] = None
    street_confidence: Optional[float] = None
    building_confidence: Optional[float] = None
    match_type: Optional[str] = None
    provider: Optional[str] = None
    attribution: Optional[str] = None


class GeocodingProvider(Protocol):
    def geocode(self, address: str, *, city: Optional[str], country: Optional[str], limit: int) -> list[GeoResult]:
        ...


_LOCALITY_MARKER = re.compile(
    r'(?:^|[,;])\s*(?:г\.|город\s+|с\.|село\s+|деревня\s+|пос[её]лок\s+|пгт\s+)', re.I
)


def _current_city_name():
    from ...city_context import current_city
    from ...settings.settings_loader import _CITY_FORMS, settings

    code = current_city()
    configured = settings.features.get('city_name')
    if configured:
        return configured
    try:
        from ...city import city_name_forms
        forms = city_name_forms(code)
    except Exception:
        forms = None
    forms = forms or _CITY_FORMS.get(code)
    if not forms or not forms.get('nom'):
        raise GeocodingError(f'No city name configured for {code!r}')
    return forms['nom']


class GeoClient:
    """Geocode with the current city or an explicitly supplied locality.

    Set ``address_has_locality`` when the address already includes its city,
    village or country. ``city`` overrides the current city's default.
    Results are candidates, not verified venue locations.
    """

    def __init__(self, provider: Optional[GeocodingProvider] = None):
        if provider is None:
            path = config_value('GEO_PROVIDER') or 'davai_s_nami_bot.helper.geo.geoapify:GeoapifyProvider'
            try:
                module_name, class_name = path.split(':', 1)
                provider_class = getattr(import_module(module_name), class_name)
            except (ImportError, AttributeError, ValueError):
                raise GeocodingError('Invalid GEO_PROVIDER configuration') from None
            provider = provider_class()
        self.provider = provider

    def geocode(self, address: str, *, city: Optional[str] = None,
                country: Optional[str] = None, address_has_locality: bool = False,
                limit: int = 5) -> list[GeoResult]:
        if not isinstance(address, str) or not address.strip():
            raise ValueError('address must not be empty')
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 5:
            raise ValueError('limit must be between 1 and 5')
        if city is not None and (not isinstance(city, str) or not city.strip()):
            raise ValueError('city must not be empty')
        if country is not None and (not isinstance(country, str) or not country.strip()):
            raise ValueError('country must not be empty')
        if city is not None and address_has_locality:
            raise ValueError('city and address_has_locality are mutually exclusive')
        if city is None and not address_has_locality and not _LOCALITY_MARKER.search(address):
            city = _current_city_name()
        return self.provider.geocode(address.strip(), city=city.strip() if city else None,
                                     country=country.strip() if country else None, limit=limit)


def config_value(name):
    value = os.environ.get(name)
    if value is not None:
        return value
    from dotenv import dotenv_values
    return dotenv_values(Path(__file__).resolve().parents[3] / '.env').get(name)


_RESERVE_SCRIPT = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 86400000)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
if redis.call('ZCOUNT', KEYS[1], '(' .. (now - 1000), '+inf') >= 5 then return -1 end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('EXPIRE', KEYS[1], 86401)
return 1
"""


class RedisGeocodingQuota:
    """Shared rolling 24-hour and per-second request guard."""

    def __init__(self, redis_client, daily_limit: int = 3000):
        if isinstance(daily_limit, bool) or not isinstance(daily_limit, int) or not 1 <= daily_limit <= 3000:
            raise ValueError('daily_limit must be between 1 and 3000')
        self.redis = redis_client
        self.daily_limit = daily_limit

    def reserve(self):
        try:
            result = self.redis.eval(_RESERVE_SCRIPT, 1, 'geoapify:requests:rolling',
                                     self.daily_limit, uuid4().hex)
        except Exception:
            raise GeocodingError('Geocoding quota storage is unavailable') from None
        if result == 0:
            raise GeocodingLimitError('Geocoding daily request limit reached')
        if result == -1:
            raise GeocodingLimitError('Geocoding per-second request limit reached')
        if result != 1:
            raise GeocodingError('Unexpected geocoding quota response')
