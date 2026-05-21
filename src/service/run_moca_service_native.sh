#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCA_SERVICE_DIR="${SCRIPT_DIR}/moca_service"
MOCA_APP_DIR="${MOCA_SERVICE_DIR}/app"
VENV_DIR="${VENV_DIR:-${MOCA_SERVICE_DIR}/.venv}"

if [[ ! -d "${MOCA_APP_DIR}" ]]; then
  echo "moca_service app directory not found: ${MOCA_APP_DIR}" >&2
  exit 1
fi

if [[ ! -f "${MOCA_APP_DIR}/main.py" ]]; then
  echo "moca_service entrypoint not found: ${MOCA_APP_DIR}/main.py" >&2
  exit 1
fi

if [[ -f "${VENV_DIR}/pyvenv.cfg" ]] && grep -q "include-system-site-packages = false" "${VENV_DIR}/pyvenv.cfg"; then
  echo "Updating Python virtual environment to include ROS system packages: ${VENV_DIR}"
  python3 -m venv --system-site-packages "${VENV_DIR}"
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Creating Python virtual environment: ${VENV_DIR}"
  python3 -m venv --system-site-packages "${VENV_DIR}"
fi

if [[ ! -f "${VENV_DIR}/.requirements.stamp" ]] || ! cmp -s "${MOCA_SERVICE_DIR}/requirements.txt" "${VENV_DIR}/.requirements.stamp"; then
  echo "Installing Python dependencies for moca_service..."
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${MOCA_SERVICE_DIR}/requirements.txt"
  cp "${MOCA_SERVICE_DIR}/requirements.txt" "${VENV_DIR}/.requirements.stamp"
fi

# Defaults mirror docker-compose.operation.yml, adjusted for a native host.
export MOCA_SERVICE_NAME="${MOCA_SERVICE_NAME:-moca_service}"
export MOCA_SERVICE_HOST="${MOCA_SERVICE_HOST:-0.0.0.0}"
export MOCA_SERVICE_PORT="${MOCA_SERVICE_PORT:-9001}"

export MOCA_DB_HOST="${MOCA_DB_HOST:-127.0.0.1}"
export MOCA_DB_PORT="${MOCA_DB_PORT:-3307}"
export MOCA_DB_USER="${MOCA_DB_USER:-business_user}"
export MOCA_DB_PASSWORD="${MOCA_DB_PASSWORD:-business_password}"
export MOCA_DB_NAME="${MOCA_DB_NAME:-business}"

export MOCA_ADMIN_GUI_HOST="${MOCA_ADMIN_GUI_HOST:-0.0.0.0}"
export MOCA_ADMIN_GUI_PORT="${MOCA_ADMIN_GUI_PORT:-9002}"
export ADMIN_GUI_HOST="${ADMIN_GUI_HOST:-127.0.0.1}"
export ADMIN_GUI_PORT="${ADMIN_GUI_PORT:-9000}"

export MOCA_TCP_TIMEOUT_SEC="${MOCA_TCP_TIMEOUT_SEC:-3.0}"

cd "${MOCA_SERVICE_DIR}"

echo "Starting native moca_service"
echo "  app:                 ${MOCA_APP_DIR}"
echo "  web service server:  ${MOCA_SERVICE_HOST}:${MOCA_SERVICE_PORT}"
echo "  admin gui listener:  ${MOCA_ADMIN_GUI_HOST}:${MOCA_ADMIN_GUI_PORT}"
echo "  admin gui peer:      ${ADMIN_GUI_HOST}:${ADMIN_GUI_PORT}"
echo "  db:                  ${MOCA_DB_HOST}:${MOCA_DB_PORT}/${MOCA_DB_NAME}"
echo "  venv:                ${VENV_DIR}"

exec "${VENV_DIR}/bin/python" -m app.main
