#!/bin/bash
# ============================================================
# run_slam.sh — vic_pinky SLAM 맵 빌드 (slam_toolbox + rviz + teleop)
# 실행: bash run_slam.sh
# 동작:
#   1) 로컬 ROS 환경(domain=22) + moca ws source
#   2) 로봇 bringup 자동 기동(없으면)
#   3) 토픽 확인(/scan_filtered, /tf, /odom)
#   4) slam_toolbox + rviz2 + teleop_twist_keyboard(gnome-terminal) 동시 실행
#   5) Ctrl+C 또는 rviz/slam 종료 시 모두 정리
# 맵 저장: 별도 터미널에서  bash save_map.sh <map_name>
# ============================================================

# 스크립트 위치 기반 워크스페이스 루트 — clone 위치 무관 작동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"
ROBOT_DOMAIN_ID="${ROBOT_DOMAIN_ID:-22}"

TELEOP_SPEED="${TELEOP_SPEED:-0.15}"
TELEOP_TURN="${TELEOP_TURN:-1.0}"

LOG_DIR="/tmp/moca_slam"
mkdir -p "$LOG_DIR"
SLAM_LOG="$LOG_DIR/slam_toolbox.log"
RVIZ_LOG="$LOG_DIR/rviz.log"

echo "======================================================"
echo " vic_pinky SLAM 맵 빌드"
echo "======================================================"

# ── Step 1. 환경 ─────────────────────────────────────────
export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
source /opt/ros/jazzy/setup.bash
[ -f "$WS/install/setup.bash" ] && source "$WS/install/setup.bash" || {
    echo " [ERROR] moca 워크스페이스 미빌드 — 'cd $WS && colcon build' 후 재시도"; exit 1;
}

echo " ROBOT         : $ROBOT_USER@$ROBOT_IP"
echo " ROS_DOMAIN_ID : $ROS_DOMAIN_ID  (robot=$ROBOT_DOMAIN_ID)"
echo " 로그          : $LOG_DIR/"
echo "------------------------------------------------------"

# ── Step 2. 사전 점검 + 로봇 bringup ─────────────────────
ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1 || { echo " [ERROR] 로봇 ping 실패"; exit 1; }
echo " [OK]  ping $ROBOT_IP"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"
RSSH_F="sshpass -p $ROBOT_PASS ssh -f $SSH_OPTS $ROBOT_USER@$ROBOT_IP"

if $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null"; then
    echo " [OK]  bringup 실행 중"
else
    echo " [INFO] bringup 기동 (ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID)..."
    $RSSH_F "mkdir -p ~/logs && setsid nohup bash -c 'export ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID; source /opt/ros/jazzy/setup.bash; source ~/vicpinky_ws/install/setup.bash; exec ros2 launch vicpinky_bringup bringup.launch.xml' </dev/null >~/logs/bringup.log 2>&1 &"
    sleep 8
    $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null" || { echo " [ERROR] bringup 기동 실패"; $RSSH 'tail -40 ~/logs/bringup.log'; exit 1; }
    echo " [OK]  bringup 기동"
fi

# ── Step 3. 토픽 대기 ────────────────────────────────────
echo " [INFO] /scan_filtered, /tf 대기..."
ros2 daemon stop >/dev/null 2>&1
ros2 daemon start >/dev/null 2>&1
SCAN_OK=0; TF_OK=0
for i in 1 2 3 4 5 6 7 8 9 10; do
    TL=$(ros2 topic list 2>/dev/null)
    [ $SCAN_OK -eq 0 ] && echo "$TL" | grep -qE "^/scan_filtered$" && SCAN_OK=1 && echo " [OK]  /scan_filtered"
    [ $TF_OK   -eq 0 ] && echo "$TL" | grep -qE "^/tf$"            && TF_OK=1   && echo " [OK]  /tf"
    [ $SCAN_OK -eq 1 ] && [ $TF_OK -eq 1 ] && break
    sleep 1
done
[ $SCAN_OK -eq 0 ] && echo " [WARN] /scan_filtered 미확인 — 매핑 안 될 수 있음"
[ $TF_OK   -eq 0 ] && echo " [WARN] /tf 미확인"

# ── Step 4. slam_toolbox + rviz + teleop 실행 ────────────
echo " [INFO] slam_toolbox 시작 (로그: $SLAM_LOG)..."
ros2 launch vicpinky_navigation map_building.launch.xml > "$SLAM_LOG" 2>&1 &
SLAM_PID=$!
sleep 2

echo " [INFO] rviz2 시작 (로그: $RVIZ_LOG)..."
ros2 launch vicpinky_navigation map_view.launch.xml > "$RVIZ_LOG" 2>&1 &
RVIZ_PID=$!
sleep 2

echo " [INFO] teleop 창 팝업 (속도 lin=$TELEOP_SPEED ang=$TELEOP_TURN)..."
gnome-terminal --title="vic_pinky teleop (SLAM)" -- bash -c "
export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
source /opt/ros/jazzy/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -p speed:=$TELEOP_SPEED -p turn:=$TELEOP_TURN
echo
echo '[teleop 종료] 엔터 키로 창 닫기'
read
"

echo "------------------------------------------------------"
echo " 매핑 진행 중. teleop 창에서 i/j/k/l/, 로 천천히 한 바퀴 돌리세요."
echo " 매핑 완료 후:  bash save_map.sh <map_name>"
echo " 종료:          이 창에서 Ctrl+C  (또는 rviz 닫기)"
echo "======================================================"

# ── 정리 trap ────────────────────────────────────────────
cleanup() {
    echo ""
    echo " [INFO] 정리 중..."
    kill $SLAM_PID $RVIZ_PID 2>/dev/null
    pkill -f "ros2 launch vicpinky_navigation map_building" 2>/dev/null
    pkill -f "ros2 launch vicpinky_navigation map_view" 2>/dev/null
    sleep 1
    echo " 종료. 맵 저장 안 했으면 slam 결과 사라집니다."
}
trap cleanup INT TERM

# rviz 또는 slam 둘 중 하나 종료될 때까지 대기
wait -n $SLAM_PID $RVIZ_PID 2>/dev/null
cleanup
