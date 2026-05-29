#!/bin/bash
# ============================================================
# run_tracking.sh — 카메라 + 사람탐지/그룹감지 + 시각화 시동 스크립트
#
# 실행: bash scripts/run_tracking.sh
#
# 시동 순서:
#   [1/3] 카메라 (usb_cam)
#   [2/3] 탐지 (dev_common — person_tracking + group_approach)
#   [3/3] 시각화 (viz_tracking)
#
# 로그 파일:
#   /tmp/log_camera.log
#   /tmp/log_dev_common.log
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
DOBY_INSTALL="$SCRIPT_DIR/../install"

# Astra 컬러 카메라 자동 탐지: by-id 이름은 고정이라 재연결로 /dev/videoN 번호가
# 바뀌어도 readlink 로 현재 실제 노드를 찾는다. 없으면 /dev/video2 로 폴백.
ASTRA_BYID=$(ls /dev/v4l/by-id/*Astra*video-index0 2>/dev/null | head -1)
if [ -n "$ASTRA_BYID" ]; then
  ASTRA_DEV=$(readlink -f "$ASTRA_BYID")
else
  ASTRA_DEV=/dev/video2
fi
VIDEO_DEVICE="${VIDEO_DEVICE:-$ASTRA_DEV}"

echo "======================================================"
echo " 카메라 + 탐지 + 시각화 시동"
echo "======================================================"
echo " WORKSPACE   : $WS"
echo " VIDEO_DEVICE: $VIDEO_DEVICE"
echo " DOMAIN_ID   : ${ROS_DOMAIN_ID:-22}"
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

SOURCE_CMD="source /opt/ros/jazzy/setup.bash && source $WS/install/local_setup.bash 2>/dev/null || true && source $DOBY_INSTALL/local_setup.bash 2>/dev/null || true && export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-22}"

# ============================================================
# [0] 기존 노드 kill
# ============================================================
echo ""
echo "[0] 기존 노드 정리 중..."
pkill -f "usb_cam_node_exe"      2>/dev/null
pkill -f "person_tracking_node"  2>/dev/null
pkill -f "group_approach_node"   2>/dev/null
pkill -f "dev_common.launch"     2>/dev/null
pkill -f "viz_tracking"          2>/dev/null
sleep 2
echo " → 정리 완료"

# ============================================================
# [1/3] 카메라 (백그라운드)
# ============================================================
echo ""
echo "[1/3] 카메라 시동... (device: $VIDEO_DEVICE)"
bash -c "$SOURCE_CMD && ros2 run usb_cam usb_cam_node_exe --ros-args \
  -r __ns:=/robot_cam \
  -p video_device:=$VIDEO_DEVICE \
  -p image_width:=640 -p image_height:=360 \
  -p framerate:=30.0 -p pixel_format:=yuyv2rgb \
  -p camera_frame_id:=robot_cam_link" \
  > /tmp/log_camera.log 2>&1 &
sleep 3
echo " → 카메라 시동 완료"

# ============================================================
# [2/3] 탐지 (백그라운드)
# ============================================================
echo ""
echo "[2/3] 탐지 시동... (YOLO 로딩 ~8초)"
bash -c "$SOURCE_CMD && ros2 launch dobi_npc_bringup dev_common.launch.py geva_image_topic:=/robot_cam/image_raw" \
  > /tmp/log_dev_common.log 2>&1 &
sleep 10
echo " → 탐지 시동 완료"

# ============================================================
# [3/3] 시각화 (창 팝업)
# ============================================================
echo ""
echo "[3/3] 시각화 시동..."
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
echo " 시동 완료!"
echo ""
echo " 카메라 장치 변경:"
echo "   VIDEO_DEVICE=/dev/video0 bash scripts/run_tracking.sh"
echo ""
echo " 문제 시 로그 확인:"
echo "   tail -f /tmp/log_camera.log"
echo "   tail -f /tmp/log_dev_common.log"
echo ""
echo " 종료:"
echo "   pkill -f usb_cam_node_exe"
echo "   pkill -f person_tracking_node"
echo "   pkill -f viz_tracking"
echo "======================================================"
