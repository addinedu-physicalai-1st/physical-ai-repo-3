#!/bin/bash
# ============================================================
# stop_dashboard.sh — run_dashboard.sh 가 띄운 ROS-only 노드 종료
#
# 사용:
#   bash <repo>/scripts/stop_dashboard.sh             # 기본 (dobi_npc 정리)
#   bash <repo>/scripts/stop_dashboard.sh --dry-run   # 매칭만 표시
#   bash <repo>/scripts/stop_dashboard.sh --quiet
#
# 본 스크립트는 stop_moca.sh 의 thin wrapper. mode_manager + task_orchestrator
# 정리에 충분.
#
# 카메라 점유 / audio sink mute / ros2 daemon stale cache cleanup 까지
# stop_moca.sh 가 자동 처리.
#
# 별도 teleop/operator UI 는 --with-ui 사용 시에만 정리.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/stop_moca.sh" "$@"
