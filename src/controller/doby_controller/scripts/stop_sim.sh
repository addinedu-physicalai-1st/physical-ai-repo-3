#!/bin/bash
# ============================================================
# stop_sim.sh — run_sim.sh 가 띄운 풀 스택 종료
#
# 종료 대상:
#   1. 운영 UI (mode_manager + opserver_node) — stop_moca.sh
#   2. Gazebo + Nav2 + RViz — run_nav2_sim.sh --stop
#
# 사용:
#   bash <repo>/scripts/stop_sim.sh
# ============================================================

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[stop_sim] $*"; }

log "Step 1/2 — 운영 UI + dobi_npc 노드 정리"
bash "$SCRIPT_DIR/stop_moca.sh" --quiet
echo ""

log "Step 2/2 — Gazebo + Nav2 + RViz 정리"
bash "$SCRIPT_DIR/run_nav2_sim.sh" --stop

echo ""
log "✓ 시뮬 풀 스택 정리 완료"
