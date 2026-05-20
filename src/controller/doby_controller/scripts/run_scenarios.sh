#!/bin/bash
# ============================================================
# run_scenarios.sh — 운영 UI 자동 시나리오 러너 (pytest 옵션 A)
#
# 전제: bash scripts/run_sim.sh 또는 bash scripts/run_dashboard.sh 사전 기동.
#
# 사용:
#   bash <repo>/scripts/run_scenarios.sh                # 전체 9 시나리오
#   bash <repo>/scripts/run_scenarios.sh -k s5          # S5 만
#   bash <repo>/scripts/run_scenarios.sh -v             # verbose
#   MOCA_OPSERVER_URL=http://localhost:9000 bash run_scenarios.sh  # 포트 override
#
# 시나리오 S1-S9: 계획서 §10.1 자동 시나리오 정합.
#
# 본 스크립트는 ROS 환경 source 불필요 (pytest 가 REST/WS 만 호출).
# 단 시뮬 풀스택은 사전 기동되어야 함.
# ============================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { echo "[run_scenarios] $*"; }

# 사전 검증 — opserver 응답 확인
URL="${MOCA_OPSERVER_URL:-http://localhost:8800}"
if ! curl -fsS "${URL}/api/v1/health" >/dev/null 2>&1; then
    log "★ opserver 응답 없음 ($URL)"
    log "  사전 기동 필요: bash $SCRIPT_DIR/run_sim.sh"
    log "  또는 (UI 단독): bash $SCRIPT_DIR/run_dashboard.sh"
    exit 1
fi
log "✓ opserver 응답 OK ($URL)"

# pytest 실행
cd "$WS"
exec python3 -m pytest tests/integration/test_ui_scenarios.py "$@"
