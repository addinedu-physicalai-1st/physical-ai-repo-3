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
#   2026-05-27 ROS 노드 백그라운드 실행 — Tracking Viz 창 하나만 표시
#   2026-05-27 시나리오 자동화 — engaging 모드로 시작하여 자동 전환
#
# 추종 시나리오 전체 흐름 (자동):
#   ① 사람 탐지/그룹 클러스터링 (dev_common — always-on)
#   ② 그룹 접근 (approach_controller — RPi, /customer_pose 기반 PD제어)
#   ③ close_threshold 도달 → engaging 모드 자동 전환
#      (게임/아이스브레이크 + GEVA 감정분석 시작)
#   ④ 감정 valence >= threshold → target_selector가 customer_id 확정
#      → follow 모드 자동 전환
#   ⑤ 1인 추종 (follow_controller — RPi)
#
# 시동 순서:
#   [0] 기존 노드 kill (중복 방지)
#   [1/4] RPi vicpinky bringup (run_vic_bringup.sh via SSH)
#   [2/4] RPi mobility_controller (approach + follow controller)
#   [3/4] 카메라 (run_robot_cam.sh)
#   [4/4] 노트북 dev_common + mode_engaging (engaging 모드로 시작)
#   [auto] engaging 모드 전환 (이후 follow 전환은 target_selector 자동 처리)
#   [viz] Tracking Viz 창 하나만 팝업
#
# 로그 파일 (문제 발생 시 확인):
#   /tmp/log_rpi_bringup.log
#   /tmp/log_mobility_ctrl.log
#   /tmp/log_robot_cam.log
#   /tmp/log_dev_common.log
#   /tmp/log_mode_engaging.log
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

# 터미널 에뮬레이터 확인 (Tracking Viz 창 전용)
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
pkill -f "mode_engaging.launch"  2>/dev/null
pkill -f "viz_tracking"          2>/dev/null
sleep 3
echo " → 정리 완료"

# ============================================================
# [1/4] RPi vicpinky bringup (백그라운드, 창 없음)
# ============================================================
echo ""
echo "[1/4] RPi vicpinky bringup 시동..."
bash -c "
    source /opt/ros/jazzy/setup.bash
    export ROS_DOMAIN_ID=22
    bash $SCRIPT_DIR/run_vic_bringup.sh
" > /tmp/log_rpi_bringup.log 2>&1 &
sleep 12

# ============================================================
# [2/4] RPi mobility_controller (백그라운드, 창 없음)
# ============================================================
echo ""
echo "[2/4] RPi mobility_controller 시동..."
sshpass -p '1' ssh -o StrictHostKeyChecking=no vic@$ROBOT_IP \
    "source /opt/ros/jazzy/setup.bash && source ~/doby_controller/install/setup.bash && export ROS_DOMAIN_ID=22 && export ROS_STATIC_PEERS=$LAPTOP_IP && export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET && ros2 launch mobility_controller mobility_controller.launch.py" \
    > /tmp/log_mobility_ctrl.log 2>&1 &
sleep 5

# ============================================================
# [3/4] 카메라 (터미널 유지 — SSH 세션 안정성 필요)
# ============================================================
echo ""
echo "[3/4] 카메라 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="Camera" -- bash -c "
        $SOURCE_CMD
        IMAGE_HEIGHT=360 bash $SCRIPT_DIR/run_robot_cam.sh
        echo '--- 카메라 종료. Enter로 창 닫기 ---'
        read
    " &
else
    xterm -title "Camera" -e bash -c "
        $SOURCE_CMD
        IMAGE_HEIGHT=360 bash $SCRIPT_DIR/run_robot_cam.sh
        echo '--- 카메라 종료. Enter로 창 닫기 ---'
        read
    " &
fi
sleep 5

# ============================================================
# [4/4] 노트북 dev_common + mode_engaging (백그라운드, 창 없음)
# ============================================================
echo ""
echo "[4/4] dev_common 시동..."
bash -c "$SOURCE_CMD && ros2 launch dobi_npc_bringup dev_common.launch.py" \
    > /tmp/log_dev_common.log 2>&1 &
sleep 8

echo ""
echo " mode_engaging 시동 (bt_executor + minigame + customer_identity + target_selector)..."
bash -c "$SOURCE_CMD && ros2 launch dobi_npc_bringup mode_engaging.launch.py" \
    > /tmp/log_mode_engaging.log 2>&1 &
sleep 8

# ============================================================
# [auto] engaging 모드 전환 (이후 follow 전환은 target_selector 자동 처리)
# ============================================================
echo ""
echo " engaging 모드 자동 전환..."
source /opt/ros/jazzy/setup.bash
source "$WS/install/local_setup.bash" 2>/dev/null || true
source "$DOBY_INSTALL/local_setup.bash" 2>/dev/null || true
export ROS_DOMAIN_ID=22
export ROS_STATIC_PEERS=$ROBOT_IP
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \
    "{requested_mode: 'engaging', params: '{}'}" 2>/dev/null \
    | grep -E "success|current_mode" || echo " (모드 전환 응답 없음 — 수동으로: ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \"{requested_mode: 'engaging', params: '{}'}\""
echo ""
echo " ※ 이후 흐름 자동:"
echo "   approach_controller → close_threshold 도달 → engaging 모드 진입"
echo "   GEVA 감정 분석 → valence >= 0.3 → target_selector → follow 모드 자동 전환"

# ============================================================
# [viz] Tracking Viz — 이 창 하나만 표시
# ============================================================
echo ""
echo " Tracking Viz 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="Tracking Viz" -- bash -c "
        $SOURCE_CMD
        python3 $WS/src/controller/doby_controller/scripts/viz_tracking.py
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
else
    xterm -title "Tracking Viz" -e bash -c "
        $SOURCE_CMD
        python3 $WS/src/controller/doby_controller/scripts/viz_tracking.py
        echo '--- 종료. Enter로 창 닫기 ---'
        read
    " &
fi

echo ""
echo "======================================================"
echo " 시동 완료! (Tracking Viz 창 하나만 표시)"
echo ""
echo " 문제 시 로그 확인:"
echo "   tail -f /tmp/log_dev_common.log"
echo "   tail -f /tmp/log_mode_engaging.log"
echo "   tail -f /tmp/log_mobility_ctrl.log"
echo "   tail -f /tmp/log_rpi_bringup.log"
echo ""
echo " 상태 확인:"
echo "   ros2 topic hz /person_tracking/tracks"
echo "   ros2 topic hz /emotion/state"
echo "   ros2 topic hz /follow/cmd_vel"
echo ""
echo " 종료:"
echo "   bash $SCRIPT_DIR/stop_follower.sh"
echo "======================================================"
