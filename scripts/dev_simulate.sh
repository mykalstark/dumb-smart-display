#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${ROOT_DIR}/.venv"

cd "${ROOT_DIR}"

if [ ! -d "${VENV_PATH}" ]; then
  echo "[DEV] Creating virtual environment at ${VENV_PATH}"
  python3 -m venv "${VENV_PATH}"
fi

source "${VENV_PATH}/bin/activate"

pip install --upgrade pip
pip install -r requirements.txt

export DISPLAY_SIMULATE=1

python -m app.main --simulate "$@"
