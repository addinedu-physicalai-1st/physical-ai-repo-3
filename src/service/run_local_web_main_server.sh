#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
REPO_SETUP="${REPO_SETUP:-${REPO_ROOT}/install/setup.bash}"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-22}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"
unset ROS_LOCALHOST_ONLY

export ROS_HOME="${ROS_HOME:-/tmp/ros_home}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/ros_logs}"

export MOCA_DOBY_CONTROLLER_ROS_ENABLED="${MOCA_DOBY_CONTROLLER_ROS_ENABLED:-false}"
export MOCA_DDOOBY_CONTROLLER_ROS_ENABLED="${MOCA_DDOOBY_CONTROLLER_ROS_ENABLED:-true}"
export MOCA_DDOOBY_CONTROLLER_ACTION_NAME="${MOCA_DDOOBY_CONTROLLER_ACTION_NAME:-ddooby/manifacture}"
export MOCA_DDOOBY_CONTROLLER_ACTION_TIMEOUT_SEC="${MOCA_DDOOBY_CONTROLLER_ACTION_TIMEOUT_SEC:-5.0}"

ACTION_PID=""
MOCA_PID=""
CLEANED_UP=0

cleanup() {
  if [[ "${CLEANED_UP}" == "1" ]]; then
    return
  fi
  CLEANED_UP=1

  echo
  echo "Stopping local web/main server stack..."

  if [[ -n "${MOCA_PID}" ]] && kill -0 "${MOCA_PID}" 2>/dev/null; then
    kill -INT "${MOCA_PID}" 2>/dev/null || true
    wait "${MOCA_PID}" 2>/dev/null || true
  fi

  if [[ -n "${ACTION_PID}" ]] && kill -0 "${ACTION_PID}" 2>/dev/null; then
    kill -INT "${ACTION_PID}" 2>/dev/null || true
    wait "${ACTION_PID}" 2>/dev/null || true
  fi

  if [[ "${KEEP_DOCKER_ON_EXIT:-0}" != "1" ]]; then
    docker compose -f "${SCRIPT_DIR}/docker-compose.operation.yml" down
  else
    echo "KEEP_DOCKER_ON_EXIT=1, leaving web_service/moca_db containers running."
  fi
}

trap cleanup EXIT INT TERM

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ROS setup not found: ${ROS_SETUP}" >&2
  exit 1
fi

if [[ ! -f "${REPO_SETUP}" ]]; then
  echo "Repo setup not found: ${REPO_SETUP}" >&2
  echo "Run from repo root first: source /opt/ros/jazzy/setup.bash && colcon build" >&2
  exit 1
fi

set +u
# shellcheck disable=SC1090
source "${ROS_SETUP}"
# shellcheck disable=SC1090
source "${REPO_SETUP}"
set -u

echo "Starting web_service / moca_db..."
docker compose -f "${SCRIPT_DIR}/docker-compose.operation.yml" up -d

echo "Starting ddooby manufacture action server..."
ros2 launch ddooby_controller manifacture_action_server.launch.py \
  hotdog_use_sim_time:=false &
ACTION_PID=$!

echo "Starting native moca_service..."
(
  cd "${SCRIPT_DIR}"
  ./run_moca_service_native.sh
) &
MOCA_PID=$!

echo
echo "Local web/main server stack is running."
echo "  ROS_DOMAIN_ID: ${ROS_DOMAIN_ID}"
echo "  Web kiosk:     https://127.0.0.1:8000/kiosk"
echo "  Health check:  curl -k https://127.0.0.1:8000/health"
echo "  Action name:   /${MOCA_DDOOBY_CONTROLLER_ACTION_NAME}"
echo
echo "Robot bringup is not started by this script."
echo "Start/keep robot bringup separately, then place a hotdog order from the kiosk."
echo "Press Ctrl+C to stop this local stack."
echo

while true; do
  if ! kill -0 "${ACTION_PID}" 2>/dev/null; then
    wait "${ACTION_PID}"
    exit $?
  fi
  if ! kill -0 "${MOCA_PID}" 2>/dev/null; then
    wait "${MOCA_PID}"
    exit $?
  fi
  sleep 1
done
