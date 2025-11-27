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
  python3-dev \
  python3-venv \
  python3-pip \
  python3-rpi.gpio \
  python3-spidev \
  python3-pil \
  python3-numpy \
  git \
  curl \
  swig \
  liblgpio-dev

echo "[INSTALL] Enabling SPI interface..."
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_spi 0 || true
else
  echo "raspi-config missing — enable SPI manually if needed."
fi

echo "[INSTALL] Creating local lib folder..."
mkdir -p "${LIB_DIR}"

# -----------------------------------------------------------------------------
# 1. Download Waveshare Library (Sparse Checkout)
# -----------------------------------------------------------------------------
if [ ! -d "${WAVESHARE_LIB_DIR}" ]; then
  echo "[INSTALL] Fetching Waveshare e-Paper Python library into ./lib/waveshare_epd..."
  TMP_DIR="$(mktemp -d)"
  
  # Sparse checkout to save disk space
  echo "[INSTALL] Performing sparse checkout..."
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

  # Copy the library to our local folder
  cp -r "${TMP_DIR}/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd" "${LIB_DIR}/"
  rm -rf "${TMP_DIR}"
else
  echo "[INSTALL] waveshare_epd already exists — skipping clone."
fi

# -----------------------------------------------------------------------------
# 2. CRITICAL PATCH: Fix GPIO 17 Conflict (Robust Version)
# -----------------------------------------------------------------------------
echo "[INSTALL] Checking for GPIO 17 conflict in epdconfig.py..."
CONFIG_FILE="${WAVESHARE_LIB_DIR}/epdconfig.py"

if [ -f "${CONFIG_FILE}" ]; then
  # We use [[:space:]]* to match any spaces/tabs safely.
  # We check if ANY line contains "RST_PIN" followed by "=" and "17".
  if grep -q "RST_PIN[[:space:]]*=[[:space:]]*17" "${CONFIG_FILE}"; then
      echo "[INSTALL] Found 'RST_PIN = 17'. Patching to 5..."
      
      # Use sed to replace 17 with 5 on lines matching RST_PIN
      sed -i 's/RST_PIN[[:space:]]*=[[:space:]]*17/RST_PIN = 5/g' "${CONFIG_FILE}"
      
      # Verify the patch
      if grep -q "RST_PIN = 5" "${CONFIG_FILE}"; then
          echo "[INSTALL] Patch applied successfully."
      else
          echo "[INSTALL] ERROR: Patch command ran but file looks unchanged. Please check ${CONFIG_FILE} manually."
      fi
  else
      # Double check if it is already 5
      if grep -q "RST_PIN[[:space:]]*=[[:space:]]*5" "${CONFIG_FILE}"; then
          echo "[INSTALL] RST_PIN is already set to 5 (good)."
      else
          echo "[INSTALL] WARNING: Could not find 'RST_PIN = 17'. Current file content matching RST_PIN:"
          grep "RST_PIN" "${CONFIG_FILE}" || echo "(No match found)"
      fi
  fi
else
  echo "[INSTALL] Warning: ${CONFIG_FILE} not found. Could not apply pin patch."
fi

# -----------------------------------------------------------------------------
# 3. Python Environment Setup
# -----------------------------------------------------------------------------
echo "[INSTALL] Creating virtualenv..."
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

# -----------------------------------------------------------------------------
# 4. Systemd Service Setup
# -----------------------------------------------------------------------------
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