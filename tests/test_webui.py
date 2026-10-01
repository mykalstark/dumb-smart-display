"""Configuration contracts exercised by the refreshed web interface."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

from app.webui import server


class WebUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        for name, value in {
            '_CONFIG_PATH': root / 'config.yml',
            '_UPLOADS_DIR': root / 'uploads',
            '_restart_service': lambda: (True, 'Display service restarting.'),
            '_get_current_version': lambda: 'test-version',
        }.items():
            mock = patch.object(server, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.client = server.app.test_client()
        server._write_user_config({
            'modules': {'enabled': ['countdown', 'clock'], 'settings': {'clock': {'custom': 'retain'}}},
            'hardware': {'pins': {'button1': 17}},
        })

    def test_pages_and_local_assets_render(self):
        for url in ['/config', '/modules', '/static/ui.css', '/static/ui.js',
                    '/static/settings.js', '/static/settings.css', '/static/location.js',
                    '/static/modules.js', '/static/modules.css']:
            with self.subTest(url=url):
                with self.client.get(url) as response:
                    self.assertEqual(response.status_code, 200)

    def test_settings_save_preserves_module_order_and_unrendered_keys(self):
        data = {
            'location__location_name': 'Studio',
            'location__address': 'Denver, Colorado, United States',
            'location__latitude': '40.5',
            'location__longitude': '-112.3',
            'modules__enabled__clock': '1',
            'modules__enabled__countdown': '1',
            'modules__enabled__system_status': '1',
            'modules__settings__countdown__events__0__name': 'Holiday',
            'modules__settings__countdown__events__0__date': '2026-12-25',
            'modules__settings__ticktick__api.timezone': 'America/Denver',
            'hardware__after_hours__start': '22:00',
        }
        response = self.client.post('/config', data=data)
        self.assertEqual(response.status_code, 302)
        cfg = server._load_user_config()
        self.assertEqual(cfg['location']['latitude'], 40.5)
        self.assertEqual(cfg['location']['address'], 'Denver, Colorado, United States')
        self.assertEqual(cfg['modules']['enabled'], ['countdown', 'clock', 'system_status'])
        self.assertEqual(cfg['modules']['settings']['clock']['custom'], 'retain')
        self.assertEqual(cfg['modules']['settings']['countdown']['events'],
                         [{'name': 'Holiday', 'date': '2026-12-25'}])
        self.assertEqual(cfg['modules']['settings']['ticktick']['api']['timezone'], 'America/Denver')
        self.assertEqual(cfg['hardware']['pins']['button1'], 17)
        self.assertEqual(cfg['hardware']['after_hours']['start'], '22:00')

    def test_module_save_uses_ordered_inputs_and_excludes_disabled_modules(self):
        response = self.client.post('/modules', data=MultiDict([
            ('module_order', 'system_status'), ('module_order', 'countdown'),
            ('module_order', 'clock'), ('module_enabled__system_status', 'on'),
            ('module_enabled__clock', 'on'),
        ]))
        self.assertEqual(response.status_code, 302)
        cfg = server._load_user_config()
        self.assertEqual(cfg['modules']['enabled'], ['system_status', 'clock'])
        self.assertEqual(cfg['modules']['settings']['clock']['custom'], 'retain')

    def test_photo_is_saved_immediately_and_survives_settings_save(self):
        response = self.client.post('/after-hours/upload', data={
            'photo': (io.BytesIO(b'fixture'), 'example.png'),
        })
        self.assertTrue(response.json['ok'])
        self.client.post('/config', data={'location__location_name': 'Studio'})
        cfg = server._load_user_config()
        self.assertEqual(cfg['hardware']['after_hours']['photo'], 'after_hours_photo.png')
        self.assertTrue((server._UPLOADS_DIR / 'after_hours_photo.png').exists())
        self.assertTrue(self.client.post('/after-hours/delete').json['ok'])
        self.assertEqual(server._load_user_config()['hardware']['after_hours']['photo'], '')

    def test_location_search_responses_and_authentication(self):
        places = [{'label': 'Denver, Colorado', 'latitude': 39.7392, 'longitude': -104.9903}]
        with patch.object(server, 'search_places', return_value=places) as lookup:
            response = self.client.post('/location/search', json={'query': 'Denver, CO'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['results'], places)
            lookup.assert_called_once_with('Denver, CO')
        for payload in [None, [], {'query': 123}]:
            self.assertEqual(self.client.post('/location/search', json=payload).status_code, 400)
        for exception, code in [(ValueError('Invalid query'), 400),
                                (server.LookupBusy('Please wait'), 429),
                                (server.LookupUnavailable('Unavailable'), 502)]:
            with patch.object(server, 'search_places', side_effect=exception):
                response = self.client.post('/location/search', json={'query': 'Denver, CO'})
                self.assertEqual(response.status_code, code)
                self.assertIn('error', response.json)
                if code == 429:
                    self.assertEqual(response.headers['Retry-After'], '1')
        server._write_user_config({'webui': {'password': 'test-password'}})
        with patch.object(server, 'search_places') as lookup:
            self.assertEqual(self.client.post('/location/search', json={'query': 'Denver, CO'}).status_code, 302)
            lookup.assert_not_called()

    def test_login_and_password_protected_routes(self):
        server._write_user_config({'webui': {'password': 'test-password'}})
        self.assertEqual(self.client.get('/config').status_code, 302)
        self.assertEqual(self.client.get('/modules').status_code, 302)
        self.assertIn(b'Welcome back.', self.client.get('/login').data)
        response = self.client.post('/login', data={'password': 'wrong'})
        self.assertIn(b'role="alert"', response.data)
        self.assertEqual(self.client.post('/login', data={'password': 'test-password'}).status_code, 302)
        self.assertEqual(self.client.get('/config').status_code, 200)


if __name__ == '__main__':
    unittest.main()
