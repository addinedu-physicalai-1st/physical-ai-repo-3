#!/bin/bash
# ============================================================
# run_3stage.sh — 3단계 실물 검증 한 번에 시동
#
# 실행: bash ~/moca/scripts/run_3stage.sh
#
# 순서:
#   1) RPi bringup (run_vic_bringup.sh — SSH 자동)
#   2) 카메라 (run_robot_cam.sh)
#   3) Nav2 (run_nav2.sh)
#   4) 전체 시스템 (dev_common.launch.py)
# ============================================================

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "======================================================"
echo " moca 3단계 실물 검증 시동"
echo "======================================================"

# 터미널 에뮬레이터 확인
if command -v gnome-terminal >/dev/null 2>&1; then
    TERM_CMD="gnome-terminal"
elif command -v xterm >/dev/null 2>&1; then
    TERM_CMD="xterm"
else
    echo " [ERROR] gnome-terminal 또는 xterm 이 필요합니다"
    exit 1
fi

SOURCE_CMD="source /opt/ros/jazzy/setup.bash && source ~/moca/install/setup.bash && export ROS_DOMAIN_ID=22"

echo " [1/4] RPi bringup 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="1. RPi Bringup" -- bash -c "
        source /opt/ros/jazzy/setup.bash
        export ROS_DOMAIN_ID=22
        bash $DIR/run_vic_bringup.sh
        echo '--- 완료. 창 닫으려면 Enter ---'
        read
    " &
else
    xterm -title "1. RPi Bringup" -e bash -c "
        source /opt/ros/jazzy/setup.bash
        export ROS_DOMAIN_ID=22
        bash $DIR/run_vic_bringup.sh
        echo '--- 완료. 창 닫으려면 Enter ---'
        read
    " &
fi

sleep 12

echo " [2/4] 카메라 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="2. Camera" -- bash -c "
        $SOURCE_CMD
        bash $DIR/run_robot_cam.sh
        read
    " &
else
    xterm -title "2. Camera" -e bash -c "
        $SOURCE_CMD
        bash $DIR/run_robot_cam.sh
        read
    " &
fi

sleep 5

echo " [3/4] Nav2 시동..."
if [ "$TERM_CMD" = "gnome-terminal" ]; then
    gnome-terminal --title="3. Nav2" -- bash -c "
        $SOURCE_CMD
        bash $DIR/run_nav2.sh
        read
    " &
else
    xterm -title "3. Nav2" -e bash -c "
        $SOURCE_CMD
        bash $DIR/run_nav2.sh
        read
    " &
fi

sleep 10

echo " [4/4] 전체 시스템 시동..."
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
echo " 종료: bash ~/moca/scripts/stop_moca.sh"
echo "======================================================"
