#!/bin/bash
# ============================================================
# run_robot_cam.sh — vic_pinky RPi USB 카메라 raw publisher 기동 (moca 용)
# 실행: bash run_robot_cam.sh
# 동작:
#   1) 로컬 ROS2 환경(domain=22, fastrtps) 세팅
#   2) 로봇 ping 점검
#   3) 로봇 측 /dev/video0 존재 + UVC 인식 확인
#   4) 로봇(vic@$ROBOT_IP) SSH → v4l2_camera_node 기동 (없으면)
#      - 카메라 실측: HCAM01N (Microdia, USB 2.0). MJPG 1280x720@30 OK
#      - 토픽: /robot_cam/image_raw (sensor_msgs/Image)
#   5) 노트북에서 /robot_cam/image_raw 토픽 발견 + hz 확인
# 종료: bash stop_robot_cam.sh
#
# 정책:
#   - 로봇 측 ros2 워크스페이스 install 불필요 — `ros2 run` 인라인 인자.
#   - 카메라 1(노트북 webcam)과 별도 프로세스. 동시 실행 가능.
#   - 카메라 아키텍처 SoT: docs/cafe_npc_camera_architecture.md §3
# ============================================================

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"
ROBOT_DOMAIN_ID="${ROBOT_DOMAIN_ID:-22}"

VIDEO_DEVICE="${VIDEO_DEVICE:-/dev/video0}"
# 기본값 YUYV 640x480 — HCAM01N + RPi5 ros-jazzy-v4l2-camera 0.7.1 실측 동작 확인.
# MJPG 1280x720은 카메라 자체는 30fps OK이나 v4l2_camera_node가 MJPG→rgb8 변환에서
# cv_bridge "Unrecognized image encoding" 예외 종료 (해당 빌드의 제약).
# Phase 후속에 MJPG 경로 정정 필요해지면 PIXEL_FORMAT=MJPG 환경변수로 재시도.
IMAGE_WIDTH="${IMAGE_WIDTH:-640}"
IMAGE_HEIGHT="${IMAGE_HEIGHT:-480}"
PIXEL_FORMAT="${PIXEL_FORMAT:-YUYV}"
CAMERA_NS="${CAMERA_NS:-/robot_cam}"
CAMERA_FRAME="${CAMERA_FRAME:-robot_cam_link}"

echo "======================================================"
echo " vic_pinky robot_cam (RPi USB 카메라 raw publisher)"
echo "======================================================"

# ── Step 1. 로컬 ROS2 환경 ──────────────────────────────────
export ROS_DOMAIN_ID="$ROBOT_DOMAIN_ID"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
# Wi-Fi multicast 차단 회피 — RPi unicast peer 명시 (2026-05-07 follow 검증 사고).
# 노트북-RPi 같은 LAN 이지만 default DDS multicast (UDP 7400) 가 일부 Wi-Fi AP/라우터에서
# drop 됨 → discovery 실패. ROS_STATIC_PEERS 로 unicast 강제. RPi 측 시동 명령에도
# LAPTOP_IP 명시 필요.
export ROS_STATIC_PEERS="$ROBOT_IP"
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
LAPTOP_IP=$(hostname -I | awk '{print $1}')
source /opt/ros/jazzy/setup.bash

echo " ROBOT         : $ROBOT_USER@$ROBOT_IP"
echo " ROS_DOMAIN_ID : $ROS_DOMAIN_ID"
echo " STATIC_PEERS  : laptop=$LAPTOP_IP  rpi=$ROBOT_IP  (unicast, multicast 우회)"
echo " VIDEO         : $VIDEO_DEVICE  $IMAGE_WIDTH x $IMAGE_HEIGHT  $PIXEL_FORMAT"
echo " TOPIC         : ${CAMERA_NS}/image_raw"
echo "------------------------------------------------------"

# ── Step 2. 사전 점검 ──────────────────────────────────────
ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1 || { echo " [ERROR] 로봇 ping 실패"; exit 1; }
echo " [OK]  ping $ROBOT_IP"
command -v sshpass >/dev/null || { echo " [ERROR] sshpass 미설치"; exit 1; }

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"
RSSH_F="sshpass -p $ROBOT_PASS ssh -f $SSH_OPTS $ROBOT_USER@$ROBOT_IP"

# ── Step 3. 로봇 측 카메라 device 확인 + USB auto-suspend 해제 ─────────
echo " [INFO] 로봇 측 $VIDEO_DEVICE 확인..."
DEV_INFO=$($RSSH "test -e $VIDEO_DEVICE && v4l2-ctl -d $VIDEO_DEVICE --info 2>/dev/null | grep -E 'Card type|Driver name'" 2>&1)
if [ -z "$DEV_INFO" ]; then
    echo " [ERROR] $VIDEO_DEVICE 미발견 또는 UVC 미인식. USB 카메라 연결 확인 필요"
    echo "         힌트: sshpass -p 1 ssh vic@$ROBOT_IP 'v4l2-ctl --list-devices'"
    exit 1
fi
echo " [OK]  $VIDEO_DEVICE 인식:"
echo "$DEV_INFO" | sed 's/^/        /'

# USB auto-suspend 해제 — suspended 상태에서 streaming 시 Protocol error.
# HCAM01N은 4-1 USB 경로. 다른 카메라 시 USB_DEVPATH 환경변수로 override.
USB_DEVPATH="${USB_DEVPATH:-/sys/bus/usb/devices/4-1/power/control}"
echo " [INFO] USB auto-suspend 해제 ($USB_DEVPATH)..."
SUSPEND_RESULT=$($RSSH "
  if [ -w $USB_DEVPATH ]; then
    echo on > $USB_DEVPATH && echo 'on (no sudo)'
  else
    echo $ROBOT_PASS | sudo -S sh -c 'echo on > $USB_DEVPATH' 2>/dev/null && cat $USB_DEVPATH
  fi
" 2>&1 | tail -1)
echo "        power/control: $SUSPEND_RESULT"

# ── Step 4. v4l2_camera_node 기동 (없을 때) ────────────────
echo " [INFO] v4l2_camera_node 상태 확인..."
if $RSSH "pgrep -f '[v]4l2_camera_node' >/dev/null"; then
    echo " [OK]  v4l2_camera_node 실행 중 (재기동 안 함)"
else
    echo " [INFO] v4l2_camera_node 기동..."
    # ros2 run 인라인 — RPi 측 워크스페이스 install 불필요.
    # 'image_size' 는 array<int> 이므로 -p 'image_size:=[1280,720]' 형식.
    $RSSH_F "mkdir -p ~/logs && setsid nohup bash -c '
      export ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID
      export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
      export ROS_STATIC_PEERS=$LAPTOP_IP
      export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
      source /opt/ros/jazzy/setup.bash
      exec ros2 run v4l2_camera v4l2_camera_node --ros-args \
        -r __ns:=$CAMERA_NS \
        -p video_device:=$VIDEO_DEVICE \
        -p pixel_format:=$PIXEL_FORMAT \
        -p output_encoding:=rgb8 \
        -p image_size:=[$IMAGE_WIDTH,$IMAGE_HEIGHT] \
        -p time_per_frame:=[1,30] \
        -p camera_frame_id:=$CAMERA_FRAME
    ' </dev/null >~/logs/robot_cam.log 2>&1 &"
    sleep 3
    if ! $RSSH "pgrep -f '[v]4l2_camera_node' >/dev/null"; then
        echo " [ERROR] v4l2_camera_node 기동 실패 — 원격 로그(~/logs/robot_cam.log) 마지막 30줄:"
        $RSSH 'tail -30 ~/logs/robot_cam.log'
        exit 1
    fi
    echo " [OK]  v4l2_camera_node 기동 완료 (원격 로그: ~/logs/robot_cam.log)"
fi

# ── Step 5. 토픽 수신 확인 ────────────────────────────────
echo " [INFO] 토픽 수신 대기..."
ros2 daemon stop >/dev/null 2>&1
ros2 daemon start >/dev/null 2>&1

TOPIC="${CAMERA_NS}/image_raw"
TOPIC_OK=0
for i in $(seq 1 10); do
    if ros2 topic list 2>/dev/null | grep -qE "^${TOPIC}\$"; then
        TOPIC_OK=1
        break
    fi
    sleep 1
done

if [ $TOPIC_OK -eq 1 ]; then
    echo " [OK]  $TOPIC 발견"
    HZ=$(timeout 4 ros2 topic hz "$TOPIC" 2>&1 | grep -oE 'average rate: [0-9.]+' | head -1 | awk '{print $3}')
    if [ -n "$HZ" ]; then
        echo " [OK]  publish rate: ${HZ} Hz (목표 $IMAGE_WIDTH x $IMAGE_HEIGHT @ 30Hz)"
    else
        echo " [WARN] hz 측정 실패 — 카메라 USB 대역폭/CPU 부하 또는 토픽 늦은 시동"
    fi
else
    echo " [WARN] $TOPIC 미발견 — DDS discovery 또는 노드 즉사 가능성"
    $RSSH 'tail -20 ~/logs/robot_cam.log' || true
fi

# ── 결과 요약 ────────────────────────────────────────────
echo "------------------------------------------------------"
if [ $TOPIC_OK -eq 1 ]; then
    echo " 결과: robot_cam 준비 완료 ✓"
else
    echo " 결과: 노드는 기동됐으나 토픽 미확인 — 위 로그 참조"
fi
echo ""
echo " 다음 단계:"
echo "   ▷ 영상 미리보기 (노트북):"
echo "       ros2 run rqt_image_view rqt_image_view ${CAMERA_NS}/image_raw"
echo ""
echo "   ▷ 종료:"
echo "       bash $(dirname "$0")/stop_robot_cam.sh"
echo "======================================================"
