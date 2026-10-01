"""Isolated web UI fixture used only by scripts/check_webui_browser.cjs."""
import signal
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import send_from_directory
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.webui import server  # noqa: E402


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with TemporaryDirectory(prefix='display-webui-check-') as directory:
        server._CONFIG_PATH = Path(directory) / 'config.yml'
        server._UPLOADS_DIR = Path(directory) / 'uploads'
        server._write_user_config({
            'location': {'location_name': 'Home', 'time_format': '12h'},
            'modules': {'enabled': ['clock', 'countdown', 'system_status']},
            'hardware': {'simulate': True},
        })
        @server.app.route('/static/uploads/<path:filename>')
        def fixture_photo(filename):
            return send_from_directory(server._UPLOADS_DIR, filename)

        server._restart_service = lambda: (True, 'Display service restarting.')
        server._get_current_version = lambda: 'test-version'
        # Updates must always be intercepted by the browser test.
        def block_update():
            return server.Response('Updates disabled in browser fixture.', status=409)
        server.app.view_functions['update_stream'] = block_update
        server.app.view_functions['update_check'] = block_update
        server.app.view_functions['do_update'] = block_update
        with make_server('127.0.0.1', 0, server.app) as http:
            print(f'READY http://127.0.0.1:{http.server_port}', flush=True)
            http.serve_forever()
