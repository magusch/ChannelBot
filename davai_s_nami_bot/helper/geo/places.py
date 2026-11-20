"""Safely geocode places without existing coordinates."""

import math
import re
import time
from datetime import datetime, timedelta, timezone

from ...database.models import Place
from ..place_match import _same_building, parse_address
from .client import GeocodingError, GeocodingLimitError, _LOCALITY_MARKER, _current_city_name


def _house_tokens(value):
    return {
        re.sub(r'\s+', '', m.group().lower()).replace('ё', 'е')
        for m in re.finditer(r'(?<!\w)\d+(?:\s*/\s*\d+|\s*к\s*\d+|\s*[а-яa-z])?(?!\w)', value or '', re.I)
    }


def _street_type(value):
    for pattern, kind in (
        (r'(?<!\w)(?:ул\.?|улица)(?!\w)', 'street'),
        (r'(?<!\w)(?:пл\.?|площадь)(?!\w)', 'square'),
        (r'(?<!\w)(?:пр\.?|просп\.?|проспект)(?!\w)', 'avenue'),
        (r'(?<!\w)(?:наб\.?|набережная)(?!\w)', 'embankment'),
        (r'(?<!\w)(?:пер\.?|переулок)(?!\w)', 'lane'),
        (r'(?<!\w)(?:бул\.?|бульвар)(?!\w)', 'boulevard'),
        (r'(?<!\w)(?:шоссе)(?!\w)', 'highway'),
        (r'(?<!\w)(?:линия)(?!\w)', 'line'),
    ):
        if re.search(pattern, value or '', re.I):
            return kind
    return None


def _locality(value):
    value = (value or '').strip().lower().replace('ё', 'е')
    return re.sub(r'^(?:городской округ|город|г\.|село|с\.|пос[её]лок|пгт)\s*', '', value).strip()


def _reliable_match(address, candidates, expected_city, min_confidence=0.9):
    """Accept only unambiguous house-level matches with matching house number."""
    numbers = _house_tokens(address)
    matches = []
    for item in candidates:
        if (item.result_type not in ('building', 'amenity') or item.match_type not in ('full_match', 'inner_part')
                or not math.isfinite(item.latitude) or not math.isfinite(item.longitude)
                or not -90 <= item.latitude <= 90 or not -180 <= item.longitude <= 180
                or item.confidence is None or item.confidence < min_confidence
                or item.city_confidence is None or item.city_confidence < min_confidence
                or (item.street_confidence is not None and item.street_confidence < min_confidence)
                or (item.building_confidence is not None and item.building_confidence < min_confidence)
                or not item.house_number or not item.street or not item.city
                or _locality(item.city) != _locality(expected_city)
                or not (_house_tokens(item.house_number) & numbers)):
            continue
        source_type, result_type = _street_type(address), _street_type(item.street)
        if source_type and result_type and source_type != result_type:
            continue
        known = parse_address(address)
        found = parse_address(f'{item.street}, {item.house_number}')
        if not any(_same_building(a, b) and (a.extra is None or a.extra == b.extra)
                   for a in known for b in found):
            continue
        matches.append(item)
    if not matches:
        return None
    first = matches[0]
    for item in matches[1:]:
        a = math.radians(item.latitude - first.latitude)
        b = math.radians(item.longitude - first.longitude)
        hav = (math.sin(a / 2) ** 2 + math.cos(math.radians(first.latitude))
               * math.cos(math.radians(item.latitude)) * math.sin(b / 2) ** 2)
        if 2 * 6371000 * math.asin(min(1, math.sqrt(hav))) > 100:
            return None
    return first


def geocode_missing_places(db, client, *, limit=30, retry_days=28, min_confidence=0.9,
                           pause_seconds=0.25, now=None):
    """Use the current city scope; never overwrite partial or existing coordinates."""
    if not 1 <= limit <= 100 or retry_days < 1 or not 0.9 <= min_confidence <= 1:
        raise ValueError('invalid place geocoding settings')
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retry_days)
    rows = db.query(Place.id, Place.city_id, Place.place_address, Place.place_city,
                    Place.geocoded_at, Place.geocoding_metadata).filter(
        Place.latitude.is_(None), Place.longitude.is_(None),
        Place.place_address.isnot(None), Place.place_address != '',
    ).order_by(Place.geocoded_at.asc().nullsfirst(), Place.id).all()
    selected = []
    skipped_locality = 0
    for row in rows:
        place_city = (row.place_city or '').strip()
        default_locality = not place_city or place_city.lower() == row.city_id.lower()
        if ((place_city.lower().startswith(row.city_id.lower() + '_'))
                or (default_locality and _LOCALITY_MARKER.search(row.place_address))):
            skipped_locality += 1
            continue
        attempted = row.geocoded_at
        if attempted and attempted.tzinfo is None:
            attempted = attempted.replace(tzinfo=timezone.utc)
        metadata = row.geocoding_metadata or {}
        if (attempted and attempted > cutoff and metadata.get('address') == row.place_address
                and metadata.get('place_city') == row.place_city):
            continue
        selected.append(row)
        if len(selected) == limit:
            break

    stats = {'selected': len(selected), 'lookups': 0, 'updated': 0,
             'unconfirmed': 0, 'changed': 0, 'skipped_locality': skipped_locality, 'error': None}
    for row in selected:
        place_city = (row.place_city or '').strip()
        city = None if not place_city or place_city.lower() == row.city_id.lower() else place_city
        city = city or _current_city_name()
        try:
            stats['lookups'] += 1
            candidates = client.geocode(row.place_address, city=city)
        except GeocodingLimitError:
            stats['error'] = 'quota'
            break
        except GeocodingError:
            stats['error'] = 'provider'
            break
        match = _reliable_match(row.place_address, candidates, city, min_confidence)
        metadata = {'address': row.place_address, 'place_city': row.place_city}
        values = {'geocoded_at': now}
        if match:
            metadata.update(provider=match.provider, formatted_address=match.formatted_address,
                            confidence=match.confidence, city_confidence=match.city_confidence,
                            result_type=match.result_type, attribution=match.attribution,
                            precision='building', review_required=False)
            values.update(latitude=match.latitude, longitude=match.longitude,
                          geocoding_status='matched')
        else:
            values['geocoding_status'] = 'not_approved'
            metadata.update(precision='unconfirmed', review_required=True)
            if candidates:
                candidate = candidates[0]
                metadata.update(provider=candidate.provider,
                                formatted_address=candidate.formatted_address,
                                confidence=candidate.confidence,
                                city=candidate.city, street=candidate.street,
                                house_number=candidate.house_number,
                                result_type=candidate.result_type,
                                candidate_latitude=candidate.latitude,
                                candidate_longitude=candidate.longitude,
                                attribution=candidate.attribution)
        values['geocoding_metadata'] = metadata
        updated = db.query(Place).filter(
            Place.id == row.id, Place.city_id == row.city_id,
            Place.place_address == row.place_address, Place.latitude.is_(None),
            Place.longitude.is_(None), Place.place_city == row.place_city,
            Place.geocoded_at == row.geocoded_at,
        ).update(values, synchronize_session=False)
        db.commit()
        stats['updated' if match and updated else 'unconfirmed' if updated else 'changed'] += 1
        if pause_seconds:
            time.sleep(pause_seconds)
    return stats
