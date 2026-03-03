#!/usr/bin/env bash
# dev_webui.sh — Launch the web configuration UI in development mode.
#
# Usage:
#   ./scripts/dev_webui.sh
#
# The server starts at http://localhost:8080 (or the port in config.yml).
# Live-reload is enabled via FLASK_DEBUG=1.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "[DEV_WEBUI] Creating virtual environment..."
  python3 -m venv .venv
fi

echo "[DEV_WEBUI] Installing / verifying dependencies..."
.venv/bin/pip install -q -r requirements.txt

echo "[DEV_WEBUI] Starting web UI in debug mode..."
echo "[DEV_WEBUI] Open: http://localhost:8080"
FLASK_DEBUG=1 .venv/bin/python -m app.webui.server
