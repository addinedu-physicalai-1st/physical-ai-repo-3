#!/bin/bash
# ============================================================
# run_follower.sh — 추종 기능 라이브 테스트 wrapper (DDS env 포함)
#
# 실행: bash ~/moca/scripts/run_follower.sh
#
# 동기 (2026-05-19):
#   run_3stage.sh 가 어제 머지된 팀원 자산 — SOURCE_CMD 에
#   ROS_STATIC_PEERS + ROS_AUTOMATIC_DISCOVERY_RANGE 누락
#   ([[project_dds_wifi_multicast]] patch 누락). PC ↔ RPi DDS discovery
#   실패로 토픽 NO PUB. CLAUDE.md §0-B (vic_pinky 의존 운영 스크립트
#   touch 0 정책) 로 doby 가 run_3stage.sh 직접 수정 불가
#   → 본 신규 wrapper 작성 (사용자 명시 승인 2026-05-19).
#
# 정책 정합:
#   - 본 신규 스크립트는 dobi_npc 측 자산 (vic_pinky 트리 외)
#   - 호출하는 기존 vic_pinky 의존 스크립트 (run_vic_bringup.sh,
#     run_robot_cam.sh, run_nav2.sh) 는 내용 0 변경, 호출만
#   - CLAUDE.md §0-B 허용 액션 ("위 스크립트 실행 — 호출만 OK") 정합
#
# 4 stage spawn (gnome-terminal 별 창):
#   [1/4] RPi bringup (run_vic_bringup.sh — 이미 떠 있으면 skip)
#   [2/4] 카메라 (run_robot_cam.sh → /robot_cam/image_raw)
#   [3/4] Nav2 (run_nav2.sh → /bt/cmd_vel publisher)
#   [4/4] dev_common.launch.py (mode_manager + 10 always-on 노드)
#
# 종료: bash <script_dir>/stop_moca.sh (PC 측만, RPi bringup 유지)
#       bash <script_dir>/stop_teleop_ui.sh --all (RPi bringup 도 종료)
#
# 환경변수:
#   ROBOT_IP=192.168.0.138  (default — RPi 고정 IP)
# ============================================================

# 스크립트 위치 기반 워크스페이스 추정 ([[feedback_relative_path_convention]])
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"

echo "======================================================"
echo " moca 추종 기능 라이브 테스트 시동"
echo " (run_3stage.sh + DDS env fix wrapper)"
echo "======================================================"
echo " WORKSPACE       : $WS"
echo " ROBOT_IP        : $ROBOT_IP"
echo " ROS_DOMAIN_ID   : 22"
echo " STATIC_PEERS    : $ROBOT_IP (Wi-Fi multicast 우회)"
echo " DISCOVERY_RANGE : SUBNET"
echo "------------------------------------------------------"

# 터미널 에뮬레이터 확인
if command -v gnome-terminal >/dev/null 2>&1; then
    TERM_CMD="gnome-terminal"
elif command -v xterm >/dev/null 2>&1; then
    TERM_CMD="xterm"
else
    echo " [ERROR] gnome-terminal 또는 xterm 이 필요합니다"
    exit 1
fi

# SOURCE_CMD — DDS env 명시 포함 (본 wrapper 의 핵심 fix)
SOURCE_CMD="source /opt/ros/jazzy/setup.bash && source $WS/install/setup.bash && export ROS_DOMAIN_ID=22 && export ROS_STATIC_PEERS=$ROBOT_IP && export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET"

# [1/4] RPi bringup — 별 env (run_vic_bringup.sh 가 자체 SSH 환경 설정)
echo " [1/4] RPi bringup 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="1. RPi Bringup" -- bash -c "
        source /opt/ros/jazzy/setup.bash
        export ROS_DOMAIN_ID=22
        bash $SCRIPT_DIR/run_vic_bringup.sh
        echo '--- 완료. 창 닫으려면 Enter ---'
        read
    " &
else
    xterm -title "1. RPi Bringup" -e bash -c "
        source /opt/ros/jazzy/setup.bash
        export ROS_DOMAIN_ID=22
        bash $SCRIPT_DIR/run_vic_bringup.sh
        echo '--- 완료. 창 닫으려면 Enter ---'
        read
    " &
fi

sleep 12

# [2/4] 카메라
echo " [2/4] 카메라 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="2. Camera" -- bash -c "
        $SOURCE_CMD
        bash $SCRIPT_DIR/run_robot_cam.sh
        read
    " &
else
    xterm -title "2. Camera" -e bash -c "
        $SOURCE_CMD
        bash $SCRIPT_DIR/run_robot_cam.sh
        read
    " &
fi

sleep 5

# [3/4] Nav2
echo " [3/4] Nav2 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="3. Nav2" -- bash -c "
        $SOURCE_CMD
        bash $SCRIPT_DIR/run_nav2.sh
        read
    " &
else
    xterm -title "3. Nav2" -e bash -c "
        $SOURCE_CMD
        bash $SCRIPT_DIR/run_nav2.sh
        read
    " &
fi

sleep 10

# [4/4] dev_common (mode_manager + always-on 10 노드)
echo " [4/4] dev_common 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="4. dev_common" -- bash -c "
        $SOURCE_CMD
        ros2 launch dobi_npc_bringup dev_common.launch.py
        read
    " &
else
    xterm -title "4. dev_common" -e bash -c "
        $SOURCE_CMD
        ros2 launch dobi_npc_bringup dev_common.launch.py
        read
    " &
fi

echo "======================================================"
echo " 터미널 4개 시동 완료"
echo " 검증 (다른 터미널):"
echo "   source /opt/ros/jazzy/setup.bash"
echo "   source $WS/install/setup.bash"
echo "   export ROS_DOMAIN_ID=22"
echo "   export ROS_STATIC_PEERS=$ROBOT_IP"
echo "   export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET"
echo "   ros2 node list"
echo "   ros2 topic hz /robot_cam/image_raw /person_tracking/tracks /bt/cmd_vel"
echo ""
echo " 종료:"
echo "   bash $SCRIPT_DIR/stop_moca.sh           # PC 측만, RPi bringup 유지"
echo "   bash $SCRIPT_DIR/stop_teleop_ui.sh --all # RPi bringup 도 종료"
echo "======================================================"
