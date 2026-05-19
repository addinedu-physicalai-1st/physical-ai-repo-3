#!/bin/bash
# ============================================================
# moca.sh — Vic Pinky moca 스택 통합 시동/종료/재시동 wrapper
#
# 실행:
#   bash moca.sh start     모든 노드 시동 (RPi bringup + usb_cam + dev_all + UI)
#   bash moca.sh stop      모든 노드 종료
#   bash moca.sh restart   stop → 8초 대기 → start (DDS discovery cleanup)
#
# 내부적으로 run_teleop_ui.sh / stop_teleop_ui.sh --all 호출.
# ============================================================

DIR="$(cd "$(dirname "$0")" && pwd)"

case "$1" in
  start)
    exec bash "$DIR/run_teleop_ui.sh"
    ;;
  stop)
    exec bash "$DIR/stop_teleop_ui.sh" --all
    ;;
  restart)
    echo "======================================================"
    echo " moca restart — stop → 8s wait → start"
    echo "======================================================"
    bash "$DIR/stop_teleop_ui.sh" --all
    echo ""
    echo " [INFO] 8초 대기 (DDS discovery + 시리얼 포트 cleanup)..."
    sleep 8
    echo ""
    exec bash "$DIR/run_teleop_ui.sh"
    ;;
  *)
    echo "사용법: bash moca.sh start | stop | restart"
    echo ""
    echo "  start    — RPi bringup + usb_cam + dev_all + 운영자 UI 시동"
    echo "  stop     — 위 모두 종료 (--all 옵션으로 RPi bringup 까지)"
    echo "  restart  — stop + 8s 대기 + start (lifecycle race 회피)"
    exit 1
    ;;
esac
