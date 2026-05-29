#!/bin/bash
# start_scout_follow.sh — scout 일원화 follow 스택 일괄 시작 (원클릭)
# RPi bringup + scout 스택(run_palm) + follow(scout_unified_follow) 를 백그라운드 기동.
# 옵션:
#   --bench          DOMAIN=99 LOCALHOST (RPi 없이 PC 벤치) — RPi bringup 스킵
#   --device=/dev/.. scout_cam 디바이스 (기본: by-id 자동탐지 → 폴백 /dev/video0)
#   --sign=N         angular_sign (기본 1)
#   -h | --help      이 도움말
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"   # repo root (physical-ai-repo-3)
SCOUT_WS="${SCOUT_WS:-$HOME/scout_reactor}"
ROBOT_IP="${ROBOT_IP:-192.168.0.138}"

BENCH=0; SCOUT_DEV=""; SIGN=1
for arg in "$@"; do
    case "$arg" in
        --bench)    BENCH=1 ;;
        --device=*) SCOUT_DEV="${arg#*=}" ;;
        --sign=*)   SIGN="${arg#*=}" ;;
        -h|--help)  sed -n '2,/^$/p' "$0" | sed 's/^# *//' ; exit 0 ;;
        *) echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
    esac
done

# scout PTZ by-id 자동탐지 (USB 재열거로 /dev/videoN 번호 바뀌므로 이름 기준)
if [ -z "$SCOUT_DEV" ]; then
    BYID=$(ls /dev/v4l/by-id/*Alcorlink*USB_2.0_Camera*index0 2>/dev/null | head -1)
    [ -n "$BYID" ] && SCOUT_DEV=$(readlink -f "$BYID") || SCOUT_DEV=/dev/video0
fi

mkdir -p /tmp/scout_follow_logs
LOG_SCOUT=/tmp/scout_follow_logs/scout.log
LOG_FOLLOW=/tmp/scout_follow_logs/follow.log

echo "======================================================"
echo " scout follow 일괄 시작 (bench=$BENCH dev=$SCOUT_DEV sign=$SIGN)"
echo "======================================================"

set +u; source /opt/ros/jazzy/setup.bash; set -u
if [ $BENCH -eq 1 ]; then
    export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
    unset RMW_IMPLEMENTATION ROS_STATIC_PEERS ROS_AUTOMATIC_DISCOVERY_RANGE 2>/dev/null
else
    export ROS_DOMAIN_ID=22 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
    export ROS_STATIC_PEERS="$ROBOT_IP" ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
    unset ROS_LOCALHOST_ONLY 2>/dev/null
fi

# ── 1) RPi bringup (실차 모드) ──
if [ $BENCH -eq 0 ]; then
    echo " [1] RPi bringup..."
    bash "$SCRIPT_DIR/run_vic_bringup.sh" || { echo " [ERROR] RPi bringup 실패 — 중단"; exit 1; }
else
    echo " [1] --bench → RPi bringup 스킵"
fi

# ── 2) scout 스택 (run_palm) 백그라운드 ──
echo " [2] scout 스택 기동 ($SCOUT_DEV) → $LOG_SCOUT"
( cd "$SCOUT_WS"; exec setsid bash scripts/run_palm.sh --device="$SCOUT_DEV" ) </dev/null >"$LOG_SCOUT" 2>&1 &
for i in $(seq 1 30); do ss -ltn 2>/dev/null | grep -q ':7701' && break; sleep 1; done
ss -ltn 2>/dev/null | grep -q ':7701' && echo "     scout 7701 up" || echo "     [WARN] 7701 안뜸 — $LOG_SCOUT 확인"

# ── 3) follow 스택 (person_tracking@scout + scout_follow_controller) 백그라운드 ──
echo " [3] follow 기동 → $LOG_FOLLOW"
( cd "$WS_ROOT"; set +u; source install/setup.bash 2>/dev/null
  exec setsid ros2 launch mobility_controller scout_unified_follow.launch.py angular_sign:="$SIGN" ) </dev/null >"$LOG_FOLLOW" 2>&1 &
for i in $(seq 1 45); do grep -q 'scout_follow_controller ready' "$LOG_FOLLOW" 2>/dev/null && break; sleep 1; done
grep -q 'scout_follow_controller ready' "$LOG_FOLLOW" 2>/dev/null && echo "     follow ready" || echo "     [WARN] follow 미확인 — $LOG_FOLLOW 확인"

echo "======================================================"
echo " 시작 완료. 손들기 → lock → 추종."
echo " 로그:  scout=$LOG_SCOUT  follow=$LOG_FOLLOW"
echo " 종료:  bash $SCRIPT_DIR/stop_scout_follow.sh$([ $BENCH -eq 1 ] && echo ' --keep-rpi')"
echo "======================================================"
