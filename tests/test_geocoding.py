"""Address lookup response handling and Nominatim usage limits."""
import unittest
from unittest.mock import Mock, patch

import requests

from app.webui import geocoding


class GeocodingTests(unittest.TestCase):
    def setUp(self):
        self.get = Mock()
        self.get.return_value.json.return_value = [
            {'display_name': 'Denver, Colorado, United States', 'lat': '39.7392', 'lon': '-104.9903'},
        ]
        for name, value in {'_cache': {}, '_last_request': float('-inf')}.items():
            mock = patch.object(geocoding, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(geocoding.requests, 'get', self.get)
        mock.start()
        self.addCleanup(mock.stop)

    def test_city_and_address_results_contain_numeric_coordinates(self):
        for query in ['Denver, CO', '123 Main St, Denver, CO']:
            with self.subTest(query=query), patch.object(geocoding, '_last_request', float('-inf')):
                results = geocoding.search_places(query)
                self.assertEqual(results, [{'label': 'Denver, Colorado, United States',
                                            'latitude': 39.7392, 'longitude': -104.9903}])
                args = self.get.call_args
                self.assertEqual(args.kwargs['params']['q'], query)
                self.assertEqual(args.kwargs['timeout'], 8)
                self.assertIn('DumbSmartDisplay', args.kwargs['headers']['User-Agent'])

    def test_repeated_searches_use_cache_including_empty_results(self):
        geocoding.search_places('Denver, CO')
        geocoding.search_places('  denver,  CO  ')
        self.assertEqual(self.get.call_count, 1)
        with patch.object(geocoding, '_last_request', float('-inf')):
            self.get.return_value.json.return_value = []
            self.assertEqual(geocoding.search_places('No matching place'), [])
            self.assertEqual(geocoding.search_places('No matching place'), [])
        self.assertEqual(self.get.call_count, 2)

    def test_cooldown_and_concurrent_lookup_prevent_extra_requests(self):
        with patch.object(geocoding.time, 'monotonic', return_value=100):
            geocoding.search_places('Denver, CO')
            with self.assertRaises(geocoding.LookupBusy):
                geocoding.search_places('Austin, TX')
        geocoding._lock.acquire()
        try:
            with self.assertRaises(geocoding.LookupBusy):
                geocoding.search_places('Austin, TX')
        finally:
            geocoding._lock.release()
        self.assertEqual(self.get.call_count, 1)

    def test_expired_cache_is_refreshed_and_cache_is_bounded(self):
        with patch.object(geocoding.time, 'monotonic', return_value=100):
            geocoding.search_places('Denver, CO')
        with patch.object(geocoding.time, 'monotonic', return_value=100 + geocoding._CACHE_TTL):
            geocoding.search_places('Denver, CO')
        self.assertEqual(self.get.call_count, 2)
        with patch.object(geocoding, '_CACHE_LIMIT', 1), patch.object(geocoding, '_last_request', float('-inf')):
            geocoding.search_places('Austin, TX')
        self.assertEqual(len(geocoding._cache), 1)

    def test_bad_coordinates_are_not_offered_as_results(self):
        self.get.return_value.json.return_value = [
            {'display_name': 'Missing', 'lat': '0'},
            {'display_name': 'Invalid', 'lat': 'NaN', 'lon': '1'},
            {'display_name': 'Invalid', 'lat': '91', 'lon': '1'},
            {'display_name': 'Invalid', 'lat': '1', 'lon': '181'},
            {'display_name': '<b>Plain text label</b>', 'lat': '1', 'lon': '2'},
        ]
        self.assertEqual(geocoding.search_places('Address query'), [
            {'label': '<b>Plain text label</b>', 'latitude': 1, 'longitude': 2},
        ])

    def test_upstream_failure_is_reported_without_caching(self):
        self.get.side_effect = requests.Timeout('provider details')
        with self.assertRaises(geocoding.LookupUnavailable) as caught:
            geocoding.search_places('Denver, CO')
        self.assertNotIn('provider details', str(caught.exception))
        self.assertFalse(geocoding._cache)
        self.assertFalse(geocoding._lock.locked())

    def test_unexpected_response_and_invalid_queries(self):
        self.get.return_value.json.return_value = {'error': 'unexpected'}
        with self.assertRaises(geocoding.LookupUnavailable):
            geocoding.search_places('Denver, CO')
        for query in ['', 'ab', 'x' * 301]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                geocoding.search_places(query)
        self.assertEqual(self.get.call_count, 1)
