#!/bin/bash
set -e

APP_DIR="${APP_DIR:-$HOME/dumb-smart-display}"
APP_USER="${APP_USER:-$(whoami)}"
SERVICE_NAME="dumb-smart-display.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
SERVICE_TEMPLATE_PATH="${APP_DIR}/systemd/dumb-smart-display.service"

# Change this if you ever rename the folder
cd "${APP_DIR}"

echo "[INSTALL] Using app directory ${APP_DIR} as user ${APP_USER}".

echo "[INSTALL] Updating apt..."
sudo apt update

echo "[INSTALL] Installing system packages..."
sudo apt install -y python3 python3-venv python3-pip git

echo "[INSTALL] Creating virtualenv..."
python3 -m venv .venv

echo "[INSTALL] Installing Python dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

if [ -f "${SERVICE_TEMPLATE_PATH}" ]; then
  echo "[INSTALL] Building systemd service file from template..."
  tmp_service="$(mktemp)"
  sed -e "s#{{APP_USER}}#${APP_USER}#g" \
      -e "s#{{APP_DIR}}#${APP_DIR}#g" "${SERVICE_TEMPLATE_PATH}" > "${tmp_service}"
else
  echo "[INSTALL] Service template missing at ${SERVICE_TEMPLATE_PATH}." >&2
  exit 1
fi

echo "[INSTALL] Copying systemd service file to ${SERVICE_PATH}..."
sudo mv "${tmp_service}" "${SERVICE_PATH}"
sudo chmod 644 "${SERVICE_PATH}"

if command -v systemctl >/dev/null 2>&1; then
  echo "[INSTALL] Reloading systemd..."
  sudo systemctl daemon-reload

  echo "[INSTALL] Enabling service..."
  sudo systemctl enable "${SERVICE_NAME}"

  echo "[INSTALL] Starting service..."
  sudo systemctl start "${SERVICE_NAME}"
fi

echo ""
echo "==========================================="
echo "   Dumb Smart Display install complete."
echo "==========================================="
