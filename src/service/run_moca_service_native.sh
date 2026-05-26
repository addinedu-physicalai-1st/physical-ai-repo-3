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
export MOCA_DOBY_CONTROLLER_ROS_ENABLED="${MOCA_DOBY_CONTROLLER_ROS_ENABLED:-true}"
export MOCA_DOBY_CONTROLLER_NODE_NAME="${MOCA_DOBY_CONTROLLER_NODE_NAME:-moca_doby_controller}"
export MOCA_DOBY_CONTROLLER_SETMODE_TIMEOUT_SEC="${MOCA_DOBY_CONTROLLER_SETMODE_TIMEOUT_SEC:-2.0}"
export MOCA_DDOOBY_CONTROLLER_ROS_ENABLED="${MOCA_DDOOBY_CONTROLLER_ROS_ENABLED:-true}"
export MOCA_DDOOBY_CONTROLLER_NODE_NAME="${MOCA_DDOOBY_CONTROLLER_NODE_NAME:-moca_ddooby_controller}"
export MOCA_DDOOBY_CONTROLLER_ACTION_NAME="${MOCA_DDOOBY_CONTROLLER_ACTION_NAME:-ddooby/manifacture}"
export MOCA_DDOOBY_CONTROLLER_ACTION_TIMEOUT_SEC="${MOCA_DDOOBY_CONTROLLER_ACTION_TIMEOUT_SEC:-2.0}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-${MOCA_DOBY_CONTROLLER_ROS_DOMAIN_ID:-99}}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-${MOCA_DOBY_CONTROLLER_DISCOVERY_RANGE:-LOCALHOST}}"

ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
MOCA_ROS_WS="${MOCA_ROS_WS:-${MOCA_SERVICE_DIR}/.ros_ws}"
MOCA_CUSTOM_MSG_PACKAGE="${MOCA_CUSTOM_MSG_PACKAGE:-${MOCA_SERVICE_DIR}/custom_msg}"
MOCA_DOBI_NPC_MSGS_PACKAGE="${MOCA_DOBI_NPC_MSGS_PACKAGE:-${MOCA_CUSTOM_MSG_PACKAGE}/dobi_npc_msgs}"
MOCA_CUSTOM_MSG_SETUP="${MOCA_CUSTOM_MSG_SETUP:-${MOCA_ROS_WS}/install/setup.bash}"
DOBY_CONTROLLER_SETUP="${DOBY_CONTROLLER_SETUP:-${SCRIPT_DIR}/../controller/doby_controller/install/setup.bash}"

if [[ "${MOCA_DOBY_CONTROLLER_ROS_ENABLED}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]] || [[ "${MOCA_DDOOBY_CONTROLLER_ROS_ENABLED}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  if [[ -f "${ROS_SETUP}" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "${ROS_SETUP}"
    set -u
  else
    echo "ROS setup not found: ${ROS_SETUP}" >&2
  fi
  if [[ -d "${MOCA_CUSTOM_MSG_PACKAGE}" ]]; then
    echo "Installing custom_msg ROS interfaces into ${MOCA_ROS_WS}"
    colcon --log-base "${MOCA_ROS_WS}/log" build \
      --base-paths "${MOCA_CUSTOM_MSG_PACKAGE}" \
      --build-base "${MOCA_ROS_WS}/build" \
      --install-base "${MOCA_ROS_WS}/install" \
      --packages-select custom_msg
  else
    echo "custom_msg package not found: ${MOCA_CUSTOM_MSG_PACKAGE}" >&2
  fi
  if [[ -d "${MOCA_DOBI_NPC_MSGS_PACKAGE}" ]]; then
    echo "Installing dobi_npc_msgs ROS interfaces into ${MOCA_ROS_WS}"
    colcon --log-base "${MOCA_ROS_WS}/log" build \
      --base-paths "${MOCA_DOBI_NPC_MSGS_PACKAGE}" \
      --build-base "${MOCA_ROS_WS}/build" \
      --install-base "${MOCA_ROS_WS}/install" \
      --packages-select dobi_npc_msgs
  else
    echo "dobi_npc_msgs package not found: ${MOCA_DOBI_NPC_MSGS_PACKAGE}" >&2
  fi
  if [[ -f "${MOCA_CUSTOM_MSG_SETUP}" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "${MOCA_CUSTOM_MSG_SETUP}"
    set -u
  else
    echo "custom_msg setup not found: ${MOCA_CUSTOM_MSG_SETUP}" >&2
  fi
  if [[ -f "${DOBY_CONTROLLER_SETUP}" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "${DOBY_CONTROLLER_SETUP}"
    set -u
  else
    echo "doby_controller setup not found: ${DOBY_CONTROLLER_SETUP}" >&2
  fi
fi

cd "${MOCA_SERVICE_DIR}"

echo "Starting native moca_service"
echo "  app:                 ${MOCA_APP_DIR}"
echo "  web service server:  ${MOCA_SERVICE_HOST}:${MOCA_SERVICE_PORT}"
echo "  admin gui listener:  ${MOCA_ADMIN_GUI_HOST}:${MOCA_ADMIN_GUI_PORT}"
echo "  admin gui peer:      ${ADMIN_GUI_HOST}:${ADMIN_GUI_PORT}"
echo "  db:                  ${MOCA_DB_HOST}:${MOCA_DB_PORT}/${MOCA_DB_NAME}"
echo "  doby ros enabled:    ${MOCA_DOBY_CONTROLLER_ROS_ENABLED}"
echo "  doby ros node:       ${MOCA_DOBY_CONTROLLER_NODE_NAME}"
echo "  ddooby ros enabled:  ${MOCA_DDOOBY_CONTROLLER_ROS_ENABLED}"
echo "  ddooby ros node:     ${MOCA_DDOOBY_CONTROLLER_NODE_NAME}"
echo "  ddooby action:       ${MOCA_DDOOBY_CONTROLLER_ACTION_NAME}"
echo "  custom_msg ws:       ${MOCA_ROS_WS}"
echo "  ros domain id:       ${ROS_DOMAIN_ID}"
echo "  ros discovery range: ${ROS_AUTOMATIC_DISCOVERY_RANGE}"
echo "  venv:                ${VENV_DIR}"

exec "${VENV_DIR}/bin/python" -m app.main
