#!/bin/bash
set -e

# Change this if you ever rename the folder
APP_DIR="$HOME/dumb-smart-display"

cd "$APP_DIR"

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

echo "[INSTALL] Copying systemd service file..."
sudo cp systemd/dumb-smart-display.service /etc/systemd/system/dumb-smart-display.service

echo "[INSTALL] Reloading systemd..."
sudo systemctl daemon-reload

echo "[INSTALL] Enabling service..."
sudo systemctl enable dumb-smart-display.service

echo "[INSTALL] Starting service..."
sudo systemctl start dumb-smart-display.service

echo ""
echo "==========================================="
echo "   Dumb Smart Display install complete."
echo "==========================================="
