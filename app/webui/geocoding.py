"""Explicit city/address searches using OpenStreetMap's Nominatim service."""
from __future__ import annotations

import math
import threading
import time
from typing import Any

import requests

_ENDPOINT = 'https://nominatim.openstreetmap.org/search'
_HEADERS = {
    'User-Agent': 'DumbSmartDisplay/1.0 (+https://github.com/mykalstark/dumb-smart-display)',
    'Accept-Language': 'en',
}
# Nominatim requires at most one request per second and caching repeated queries.
_lock = threading.Lock()
_last_request = float('-inf')
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_TTL = 86400
_CACHE_LIMIT = 128


class LookupBusy(Exception):
    """A lookup is already running or the provider's cooldown has not elapsed."""


class LookupUnavailable(Exception):
    """The geocoding service could not return usable results."""


def search_places(query: str) -> list[dict[str, Any]]:
    global _last_request
    query = ' '.join(query.split())
    if not 3 <= len(query) <= 300:
        raise ValueError('Enter a city and state or a street address (3–300 characters).')
    if not _lock.acquire(blocking=False):
        raise LookupBusy('A location search is in progress. Please try again in a moment.')
    try:
        now = time.monotonic()
        key = query.casefold()
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
        if now - _last_request < 1:
            raise LookupBusy('Please wait a moment before searching again.')
        _last_request = now
        try:
            response = requests.get(
                _ENDPOINT,
                params={'q': query, 'format': 'jsonv2', 'addressdetails': 1, 'limit': 5},
                headers=_HEADERS,
                timeout=8,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise ValueError('Unexpected geocoding response')
        except (requests.RequestException, ValueError) as exc:
            raise LookupUnavailable(
                'Location search is unavailable. Check your internet connection and try again, '
                'or enter coordinates manually.'
            ) from exc
        places = []
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            try:
                latitude, longitude = float(row['lat']), float(row['lon'])
                label = row['display_name']
            except (KeyError, ValueError, TypeError):
                continue
            if (not isinstance(label, str) or not label.strip()
                    or not math.isfinite(latitude) or not math.isfinite(longitude)
                    or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
                continue
            places.append({'label': label[:500], 'latitude': latitude, 'longitude': longitude})
        _cache.pop(key, None)
        if len(_cache) >= _CACHE_LIMIT:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), places)
        return places
    finally:
        _lock.release()
