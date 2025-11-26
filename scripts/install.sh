#!/bin/bash
set -e

APP_DIR="${APP_DIR:-$HOME/dumb-smart-display}"
APP_USER="${APP_USER:-$(whoami)}"
SERVICE_NAME="dumb-smart-display.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
SERVICE_TEMPLATE_PATH="${APP_DIR}/systemd/dumb-smart-display.service"
LIB_DIR="${APP_DIR}/lib"
WAVESHARE_LIB_DIR="${LIB_DIR}/waveshare_epd"

echo "[INSTALL] Using app directory ${APP_DIR} as user ${APP_USER}"
cd "${APP_DIR}"

echo "[INSTALL] Updating apt..."
sudo apt update

echo "[INSTALL] Installing system packages..."
sudo apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  python3-rpi.gpio \
  python3-spidev \
  python3-pil \
  python3-numpy \
  git \
  curl

echo "[INSTALL] Enabling SPI interface..."
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_spi 0 || true
else
  echo "raspi-config missing — enable SPI manually if needed."
fi

echo "[INSTALL] Creating local lib folder..."
mkdir -p "${LIB_DIR}"

if [ ! -d "${WAVESHARE_LIB_DIR}" ]; then
  echo "[INSTALL] Fetching Waveshare e-Paper Python library into ./lib/waveshare_epd..."
  TMP_DIR="$(mktemp -d)"
  
  # --- START CHANGE: Use Sparse Checkout instead of full clone ---
  echo "[INSTALL] Performing sparse checkout to save space..."
  pushd "${TMP_DIR}" > /dev/null
  git init e-Paper
  cd e-Paper
  git remote add origin https://github.com/waveshare/e-Paper.git
  git config core.sparseCheckout true
  
  # Tell git exactly which folder we want
  echo "RaspberryPi_JetsonNano/python/lib/waveshare_epd" >> .git/info/sparse-checkout
  
  # Pull only that folder (depth 1 for speed)
  git pull --depth=1 origin master
  popd > /dev/null
  # --- END CHANGE ---

  # The path to copy is now guaranteed to exist without the extra STM32 bloat
  cp -r "${TMP_DIR}/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd" "${LIB_DIR}/"
  rm -rf "${TMP_DIR}"
else
  echo "[INSTALL] waveshare_epd already exists — skipping clone."
fi

echo "[INSTALL] Creating virtualenv..."
# Only create if it doesn't exist to allow re-running script safely
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

echo "[INSTALL] Installing Python project dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "[INSTALL] Installing Waveshare PyPI driver (optional)..."
sudo pip3 install --break-system-packages waveshare-epaper || true

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
echo "  Dumb Smart Display install complete."
echo "==========================================="