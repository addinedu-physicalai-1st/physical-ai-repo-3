#!/bin/bash
# ============================================================
# run_follower.sh — 추종 시나리오 전용 시동 스크립트
#
# 실행: bash scripts/run_follower.sh
#
# 변경 이력:
#   2026-05-19 최초 작성 (run_3stage.sh DDS env fix wrapper)
#   2026-05-26 업데이트 — Nav2 제거, 중복 노드 kill 추가,
#              RPi mobility_controller 시동 추가, mode_follow 추가
#
# 추종 시나리오 (Nav2 불필요):
#   ① 사람 탐지/그룹 클러스터링 (dev_common)
#   ② 사람 접근 (approach_controller — RPi)
#   ③ 1인 customer_id 고정 (mode_follow)
#   ④ 거리/방향 유지 추종 (follow_controller — RPi)
#   ※ ⑤ 카운터 안내(동행)는 Nav2 필요 — 별도 시나리오
#
# 시동 순서:
#   [0] 기존 노드 kill (중복 방지)
#   [1/4] RPi vicpinky bringup (run_vic_bringup.sh via SSH)
#   [2/4] RPi mobility_controller (approach + follow controller)
#   [3/4] 카메라 (run_robot_cam.sh)
#   [4/4] 노트북 dev_common + mode_follow
#   [auto] follow 모드 자동 전환
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# colcon workspace root: scripts/ → doby_controller/ → controller/ → src/ → repo root
WS="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
LAPTOP_IP="${LAPTOP_IP:-192.168.0.139}"

echo "======================================================"
echo " 추종 시나리오 시동"
echo "======================================================"
echo " WORKSPACE  : $WS"
echo " ROBOT_IP   : $ROBOT_IP"
echo " LAPTOP_IP  : $LAPTOP_IP"
echo " DOMAIN_ID  : 22"
echo "------------------------------------------------------"

# 터미널 에뮬레이터 확인
if command -v gnome-terminal >/dev/null 2>&1; then
    TERM_CMD="gnome-terminal"
elif command -v xterm >/dev/null 2>&1; then
    TERM_CMD="xterm"
else
    echo "[ERROR] gnome-terminal 또는 xterm 이 필요합니다"
    exit 1
fi

# SOURCE_CMD — DDS env 포함
# doby_controller sub-workspace 도 같이 소스 (dobi_npc_identity 등 일부 패키지가 여기에만 있음)
DOBY_INSTALL="$SCRIPT_DIR/../install"
SOURCE_CMD="source /opt/ros/jazzy/setup.bash && source $WS/install/local_setup.bash 2>/dev/null || true && source $DOBY_INSTALL/local_setup.bash 2>/dev/null || true && export ROS_DOMAIN_ID=22 && export ROS_STATIC_PEERS=$ROBOT_IP && export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET"

# ============================================================
# [0] 기존 노드 kill (중복 방지)
# ============================================================
echo ""
echo "[0/4] 기존 노드 정리 중..."
pkill -f "person_tracking_node"  2>/dev/null
pkill -f "group_approach_node"   2>/dev/null
pkill -f "geva_node"             2>/dev/null
pkill -f "rapport_tracker"       2>/dev/null
pkill -f "persona_manager"       2>/dev/null
pkill -f "dialog_router"         2>/dev/null
pkill -f "face_avatar"           2>/dev/null
pkill -f "tts_node"              2>/dev/null
pkill -f "mode_manager"          2>/dev/null
pkill -f "target_selector"       2>/dev/null
pkill -f "customer_identity"     2>/dev/null
pkill -f "person_detector"       2>/dev/null
pkill -f "dev_common.launch"     2>/dev/null
pkill -f "mode_follow.launch"    2>/dev/null
sleep 3
echo " → 정리 완료"

# ============================================================
# [1/4] RPi vicpinky bringup
# ============================================================
echo ""
echo "[1/4] RPi vicpinky bringup 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="1. RPi Bringup" -- bash -c "
        source /opt/ros/jazzy/setup.bash
        export ROS_DOMAIN_ID=22
        bash $SCRIPT_DIR/run_vic_bringup.sh
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
else
    xterm -title "1. RPi Bringup" -e bash -c "
        source /opt/ros/jazzy/setup.bash
        export ROS_DOMAIN_ID=22
        bash $SCRIPT_DIR/run_vic_bringup.sh
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
fi
sleep 12

# ============================================================
# [2/4] RPi mobility_controller (approach + follow controller)
# ============================================================
echo ""
echo "[2/4] RPi mobility_controller 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="2. RPi mobility_controller" -- bash -c "
        sshpass -p '1' ssh -o StrictHostKeyChecking=no vic@$ROBOT_IP '
            source /opt/ros/jazzy/setup.bash
            source ~/doby_controller/install/setup.bash
            export ROS_DOMAIN_ID=22
            export ROS_STATIC_PEERS=$LAPTOP_IP
            export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
            ros2 launch mobility_controller mobility_controller.launch.py
        '
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
else
    xterm -title "2. RPi mobility_controller" -e bash -c "
        sshpass -p '1' ssh -o StrictHostKeyChecking=no vic@$ROBOT_IP '
            source /opt/ros/jazzy/setup.bash
            source ~/doby_controller/install/setup.bash
            export ROS_DOMAIN_ID=22
            export ROS_STATIC_PEERS=$LAPTOP_IP
            export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
            ros2 launch mobility_controller mobility_controller.launch.py
        '
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
fi
sleep 5

# ============================================================
# [3/4] 카메라
# ============================================================
echo ""
echo "[3/4] 카메라 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="3. Camera" -- bash -c "
        $SOURCE_CMD
        bash $SCRIPT_DIR/run_robot_cam.sh
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
else
    xterm -title "3. Camera" -e bash -c "
        $SOURCE_CMD
        bash $SCRIPT_DIR/run_robot_cam.sh
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
fi
sleep 5

# ============================================================
# [4/4] 노트북 dev_common + mode_follow
# ============================================================
echo ""
echo "[4/4] dev_common 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="4. dev_common" -- bash -c "
        $SOURCE_CMD
        ros2 launch dobi_npc_bringup dev_common.launch.py
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
else
    xterm -title "4. dev_common" -e bash -c "
        $SOURCE_CMD
        ros2 launch dobi_npc_bringup dev_common.launch.py
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
fi
sleep 8

echo ""
echo " mode_follow 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="5. mode_follow" -- bash -c "
        $SOURCE_CMD
        ros2 launch dobi_npc_bringup mode_follow.launch.py
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
else
    xterm -title "5. mode_follow" -e bash -c "
        $SOURCE_CMD
        ros2 launch dobi_npc_bringup mode_follow.launch.py
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
fi
sleep 8

# ============================================================
# [auto] follow 모드 전환
# ============================================================
echo ""
echo " follow 모드 자동 전환..."
source /opt/ros/jazzy/setup.bash
source "$WS/install/local_setup.bash" 2>/dev/null || true
source "$DOBY_INSTALL/local_setup.bash" 2>/dev/null || true
export ROS_DOMAIN_ID=22
export ROS_STATIC_PEERS=$ROBOT_IP
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \
    "{requested_mode: 'follow', params: '{}'}" 2>/dev/null \
    | grep -E "success|current_mode" || echo " (모드 전환 응답 없음 — 수동으로: ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \"{requested_mode: 'follow', params: '{}'}\""

echo ""
echo "======================================================"
echo " 시동 완료! 터미널 5개 실행 중"
echo ""
echo " 상태 확인:"
echo "   ros2 topic hz /person_tracking/tracks"
echo "   ros2 topic hz /emotion/state"
echo "   ros2 topic hz /follow/cmd_vel"
echo ""
echo " 종료:"
echo "   bash $SCRIPT_DIR/stop_follower.sh"
echo "======================================================"
