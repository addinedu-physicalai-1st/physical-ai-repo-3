#!/bin/bash
# stop_scout_follow.sh — scout 일원화 follow 스택 일괄 종료 (원클릭 안전 정지)
# RPi bringup(모터 disarm) + scout 스택 + follow + person_tracking + probe + e_stop 안전.
# 옵션:
#   --keep-rpi   RPi bringup 은 유지 (로컬 scout/follow 만 종료 — 벤치/DOMAIN=99 용)
#   -h | --help  이 도움말
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
KEEP_RPI=0
for arg in "$@"; do
    case "$arg" in
        --keep-rpi) KEEP_RPI=1 ;;
        -h|--help)  sed -n '2,/^$/p' "$0" | sed 's/^# *//' ; exit 0 ;;
        *) echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
    esac
done

echo "======================================================"
echo " scout follow 일괄 종료  (keep-rpi=$KEEP_RPI)"
echo "======================================================"

# ── 1) 안전: e_stop true 잠깐 발행 → twist_mux 출력 즉시 차단 (실차 모드만) ──
if [ $KEEP_RPI -eq 0 ]; then
    ( source /opt/ros/jazzy/setup.bash 2>/dev/null
      export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-22}" RMW_IMPLEMENTATION=rmw_fastrtps_cpp
      export ROS_STATIC_PEERS="$ROBOT_IP" ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
      unset ROS_LOCALHOST_ONLY
      timeout 3 ros2 topic pub -r 15 /e_stop std_msgs/msg/Bool '{data: true}' >/dev/null 2>&1 ) &
    echo " [1] e_stop true 발행(3초, mux 차단)"
fi

# ── 2) 로컬 스택 종료 (follow + scout + probe) ──
echo " [2] 로컬 스택 종료 (SIGINT → SIGKILL)..."
for pat in scout_unified_follow scout_follow_controller person_tracking_node \
           palm.launch scout_follow_bridge scout_cam scout_servo_node \
           call_detector_node palm_gesture_node scout_dashboard scout_bench_probe; do
    pkill -INT -f "$pat" 2>/dev/null
done
sleep 3
for pat in scout_follow_controller person_tracking_node scout_cam scout_servo_node \
           call_detector_node palm_gesture_node scout_dashboard scout_bench_probe; do
    pkill -9 -f "$pat" 2>/dev/null
done

# ── 3) RPi bringup 종료 (모터 disarm) ──
if [ $KEEP_RPI -eq 0 ]; then
    echo " [3] RPi bringup 종료 (모터 disarm)..."
    bash "$SCRIPT_DIR/stop_vic_bringup.sh" 2>&1 | grep -E '\[1\]|OK|종료|WARN|ERROR' || true
else
    echo " [3] --keep-rpi → RPi bringup 유지"
fi

# ── 4) 확인 ──
echo " [4] 잔존 확인..."
LEFT=$(pgrep -af 'scout_cam|call_detector_node|person_tracking_node|scout_follow_controller|palm.launch|scout_bench_probe|scout_servo_node' | grep -v pgrep)
if [ -z "$LEFT" ]; then
    echo "     로컬 전부 정지"
else
    echo "$LEFT"
    echo "     [WARN] 잔존 프로세스 — 위 PID 수동 확인"
fi
ss -ltn 2>/dev/null | grep -q ':7701' && echo "     [WARN] 7701 아직 열림" || echo "     7701 free"
echo "======================================================"
echo " 종료 완료. 재시작: scout=run_palm.sh, follow=scout_unified_follow.launch.py, RPi=run_vic_bringup.sh"
echo "======================================================"
