#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCA_SERVICE_DIR="${SCRIPT_DIR}/moca_service"
LOCAL_ROS_WS="${MOCA_SERVICE_DIR}/.ros_ws"
LOCAL_MSG_PKG="${MOCA_SERVICE_DIR}/controller_status_msgs"
VENV_DIR="${VENV_DIR:-${MOCA_SERVICE_DIR}/.venv}"

ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
LOCAL_WORKSPACE_SETUP="${LOCAL_WORKSPACE_SETUP:-${LOCAL_ROS_WS}/install/setup.bash}"

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ROS setup file not found: ${ROS_SETUP}" >&2
  echo "Set ROS_SETUP=/path/to/setup.bash if your ROS install is elsewhere." >&2
  exit 1
fi

if [[ ! -d "${MOCA_SERVICE_DIR}/app" ]]; then
  echo "moca_service app directory not found: ${MOCA_SERVICE_DIR}/app" >&2
  exit 1
fi

if [[ ! -d "${LOCAL_MSG_PKG}/msg" ]]; then
  echo "Local ROS message package not found: ${LOCAL_MSG_PKG}" >&2
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

set +u
source "${ROS_SETUP}"
set -u

if [[ ! -f "${LOCAL_WORKSPACE_SETUP}" ]]; then
  echo "Building local ROS messages for moca_service..."
  colcon --log-base "${LOCAL_ROS_WS}/log" build \
    --base-paths "${LOCAL_MSG_PKG}" \
    --build-base "${LOCAL_ROS_WS}/build" \
    --install-base "${LOCAL_ROS_WS}/install" \
    --packages-select controller_status_msgs
fi

set +u
source "${LOCAL_WORKSPACE_SETUP}"
set -u

# Defaults mirror docker-compose.operation.yml, adjusted for a native host
# moca_service talking to Docker-published ports.
export MOCA_SERVICE_NAME="${MOCA_SERVICE_NAME:-moca_service}"
export MOCA_SERVICE_HOST="${MOCA_SERVICE_HOST:-0.0.0.0}"
export MOCA_SERVICE_PORT="${MOCA_SERVICE_PORT:-9001}"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-1}"
export MOCA_ROS_ENABLED="${MOCA_ROS_ENABLED:-true}"
export MOCA_ROS_NODE_NAME="${MOCA_ROS_NODE_NAME:-moca_ros_service}"

export MOCA_DB_HOST="${MOCA_DB_HOST:-127.0.0.1}"
export MOCA_DB_PORT="${MOCA_DB_PORT:-3307}"
export MOCA_DB_USER="${MOCA_DB_USER:-business_user}"
export MOCA_DB_PASSWORD="${MOCA_DB_PASSWORD:-business_password}"
export MOCA_DB_NAME="${MOCA_DB_NAME:-business}"

export ADMIN_GUI_HOST="${ADMIN_GUI_HOST:-127.0.0.1}"
export ADMIN_GUI_PORT="${ADMIN_GUI_PORT:-9000}"

export WEB_SERVICE_HOST="${WEB_SERVICE_HOST:-127.0.0.1}"
export WEB_SERVICE_TCP_PORT="${WEB_SERVICE_TCP_PORT:-9004}"

export COOKING_CONTROLLER_BRIDGE_HOST="${COOKING_CONTROLLER_BRIDGE_HOST:-127.0.0.1}"
export COOKING_CONTROLLER_BRIDGE_PORT="${COOKING_CONTROLLER_BRIDGE_PORT:-9005}"
export SERVING_CONTROLLER_BRIDGE_HOST="${SERVING_CONTROLLER_BRIDGE_HOST:-127.0.0.1}"
export SERVING_CONTROLLER_BRIDGE_PORT="${SERVING_CONTROLLER_BRIDGE_PORT:-9006}"

export VISION_SERVICE_HOST="${VISION_SERVICE_HOST:-ai-server.local}"
export VISION_SERVICE_TCP_PORT="${VISION_SERVICE_TCP_PORT:-9003}"

cd "${MOCA_SERVICE_DIR}"

echo "Starting native moca_service"
echo "  service: ${MOCA_SERVICE_HOST}:${MOCA_SERVICE_PORT}"
echo "  db:      ${MOCA_DB_HOST}:${MOCA_DB_PORT}/${MOCA_DB_NAME}"
echo "  web tcp: ${WEB_SERVICE_HOST}:${WEB_SERVICE_TCP_PORT}"
echo "  ros:     enabled=${MOCA_ROS_ENABLED}, domain=${ROS_DOMAIN_ID}, node=${MOCA_ROS_NODE_NAME}"
echo "  msg ws:  ${LOCAL_ROS_WS}"
echo "  venv:    ${VENV_DIR}"

exec "${VENV_DIR}/bin/python" -m app.main
