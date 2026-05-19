#!/bin/bash
# ============================================================
# stop_dashboard.sh — run_dashboard.sh 가 띄운 노드 종료
#
# 사용:
#   bash <repo>/scripts/stop_dashboard.sh             # 기본 (opserver + dobi_npc 정리)
#   bash <repo>/scripts/stop_dashboard.sh --dry-run   # 매칭만 표시
#   bash <repo>/scripts/stop_dashboard.sh --quiet
#
# 본 스크립트는 stop_moca.sh 의 thin wrapper. mode_manager + opserver_node
# (run_dashboard.sh 가 띄운 2 노드) 정리에 충분.
#
# 카메라 점유 / audio sink mute / ros2 daemon stale cache cleanup 까지
# stop_moca.sh 가 자동 처리.
#
# 브라우저 탭은 그대로 유지 — 사용자가 닫음.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/stop_moca.sh" "$@"
