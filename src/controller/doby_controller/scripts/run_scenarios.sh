#!/bin/bash
# ============================================================
# run_scenarios.sh — ROS-only 운영 시나리오 러너
#
# 전제: bash scripts/run_sim.sh 또는 bash scripts/run_dashboard.sh 사전 기동.
#
# 사용:
#   bash <repo>/scripts/run_scenarios.sh                # 전체 9 시나리오
#   bash <repo>/scripts/run_scenarios.sh -k s5          # S5 만
#   bash <repo>/scripts/run_scenarios.sh -v             # verbose
# ============================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { echo "[run_scenarios] $*"; }

set +u
source /opt/ros/jazzy/setup.bash
source "$WS/install/setup.bash"
set -u

# 사전 검증 — ROS 서비스 확인
if ! ros2 service list | grep -qx '/task/request_serving'; then
    log "★ /task/request_serving 서비스 없음"
    log "  사전 기동 필요: bash $SCRIPT_DIR/run_sim.sh"
    log "  또는 (ROS-only 공통층): bash $SCRIPT_DIR/run_dashboard.sh"
    exit 1
fi
log "✓ ROS-only task service 확인 OK"

exec bash "$SCRIPT_DIR/run_demo_scenario.sh" "$@"
