"""Geoapify geocoding provider."""

import requests

from .client import GeocodingError, GeocodingLimitError, GeoResult, RedisGeocodingQuota, config_value


class GeoapifyProvider:
    URL = 'https://api.geoapify.com/v1/geocode/search'

    def __init__(self, token=None, quota=None, session=None, daily_limit=3000, language='ru'):
        if token is None:
            token = config_value('GEOAPIFY_TOKEN')
        self.token = token
        if not self.token or not self.token.strip():
            raise GeocodingError('GEOAPIFY_TOKEN is not configured')
        self.session = session or requests.Session()
        self.language = language
        if quota is None:
            from ...celery_app import redis_client
            quota = RedisGeocodingQuota(redis_client, daily_limit)
        self.quota = quota

    def geocode(self, address, *, city=None, country=None, limit=5):
        text = ', '.join(part for part in (address, city, country) if part)
        params = {'text': text, 'format': 'json', 'limit': limit, 'apiKey': self.token,
                  'bias': 'countrycode:none', 'lang': self.language}
        self.quota.reserve()
        try:
            response = self.session.get(self.URL, params=params,
                                        headers={'Accept': 'application/json'}, timeout=15)
        except requests.RequestException:
            raise GeocodingError('Geoapify request failed') from None
        if response.status_code == 429:
            raise GeocodingLimitError('Geoapify rate or account quota exceeded')
        if response.status_code != 200:
            raise GeocodingError(f'Geoapify returned HTTP {response.status_code}')
        try:
            data = response.json()
            rows = data['results']
            if not isinstance(rows, list):
                raise ValueError
            return [self._result(row) for row in rows]
        except (ValueError, TypeError, KeyError, AttributeError):
            raise GeocodingError('Invalid Geoapify response') from None

    @staticmethod
    def _result(row):
        lat, lon = float(row['lat']), float(row['lon'])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError('invalid coordinates')
        rank = row.get('rank') or {}
        source = row.get('datasource') or {}
        return GeoResult(
            latitude=lat, longitude=lon, formatted_address=row.get('formatted') or '',
            city=row.get('city') or row.get('town') or row.get('village'),
            region=row.get('state'), country=row.get('country'),
            country_code=row.get('country_code'), street=row.get('street'),
            house_number=row.get('housenumber'), result_type=row.get('result_type'),
            confidence=rank.get('confidence'), city_confidence=rank.get('confidence_city_level'),
            street_confidence=rank.get('confidence_street_level'),
            building_confidence=rank.get('confidence_building_level'),
            match_type=rank.get('match_type'), provider='geoapify',
            attribution=source.get('attribution'),
        )
