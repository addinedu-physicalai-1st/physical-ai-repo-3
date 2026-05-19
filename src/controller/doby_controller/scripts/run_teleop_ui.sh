#!/bin/bash
# ============================================================
# run_teleop_ui.sh — vic_pinky 카메라 + 키보드 teleop 웹 UI
# 실행: bash run_teleop_ui.sh   →  브라우저: http://localhost:8765
# 동작:
#   1) 로컬 ROS2 환경(domain=22, default multicast) 세팅
#   2) 로봇(vic@$ROBOT_IP) SSH:
#        - vicpinky_bringup (없으면 기동)
#        - usb_cam (없으면 기동, /image_raw + /image_raw/compressed)
#   3) /odom, /image_raw/compressed 토픽 수신 확인
#   4) FastAPI 서버 실행 (포그라운드, port 8765)
# ============================================================

# 스크립트 위치 기반 워크스페이스 루트 — clone 위치 무관 작동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$WS/.venv"

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"
ROBOT_DOMAIN_ID="${ROBOT_DOMAIN_ID:-22}"

# CAM_DEV 빈 값 = HCAM01N 자동 검출 (RPi 부팅/replug 마다 video index 가
# 바뀌어도 v4l2 Card type 으로 찾아냄). 환경변수로 명시 시 그 값 그대로 사용.
CAM_DEV="${CAM_DEV:-}"
CAM_W="${CAM_W:-640}"
CAM_H="${CAM_H:-480}"
CAM_FPS="${CAM_FPS:-30}"

PORT="${PORT:-8765}"

echo "======================================================"
echo " vic_pinky Teleop UI  (브라우저 웹)"
echo "======================================================"

# ── Step 1. 로컬 ROS2 환경 ──────────────────────────────────
export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
# Wi-Fi multicast 차단 회피 — RPi unicast peer 명시 (2026-05-07 follow 검증 사고).
# 노트북-RPi 같은 LAN(192.168.0.0/24) 이지만 ROS2 jazzy default discovery 의 multicast
# (UDP 7400) 가 일부 Wi-Fi AP/라우터에서 drop 됨 → DDS discovery 완전 실패.
# ROS_STATIC_PEERS 로 unicast 강제. RPi 측 시동 명령에도 LAPTOP_IP 명시 필요.
export ROS_STATIC_PEERS="$ROBOT_IP"
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
LAPTOP_IP=$(hostname -I | awk '{print $1}')
source /opt/ros/jazzy/setup.bash
# moca 워크스페이스 (vicpinky_navigation launch — UI 내 SLAM 시작용)
if [ -f "$WS/install/setup.bash" ]; then
    source "$WS/install/setup.bash"
else
    echo " [WARN] $WS/install/setup.bash 없음 — UI 내 SLAM 시작 불가 ('colcon build' 필요)"
fi

echo " ROBOT         : $ROBOT_USER@$ROBOT_IP"
echo " ROS_DOMAIN_ID : $ROS_DOMAIN_ID  (robot=$ROBOT_DOMAIN_ID)"
echo " STATIC_PEERS  : laptop=$LAPTOP_IP  rpi=$ROBOT_IP  (unicast, multicast 우회)"
echo " camera        : ${CAM_DEV:-(auto-detect HCAM01N)}  ${CAM_W}x${CAM_H}@${CAM_FPS}"
echo " UI            : http://localhost:$PORT"
echo "------------------------------------------------------"

# ── Step 2. 사전 점검 ──────────────────────────────────────
# 이전 teleop_server 프로세스 정리 (포트 충돌 방지)
if fuser "$PORT/tcp" >/dev/null 2>&1; then
    echo " [INFO] 포트 $PORT 정리 중..."
    fuser -k "$PORT/tcp" 2>/dev/null
    sleep 1
fi
ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1 || { echo " [ERROR] 로봇 ping 실패"; exit 1; }
echo " [OK]  ping $ROBOT_IP"
command -v sshpass >/dev/null || { echo " [ERROR] sshpass 미설치"; exit 1; }
[ -d "$VENV" ] || { echo " [ERROR] $VENV 없음"; exit 1; }

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"
RSSH_F="sshpass -p $ROBOT_PASS ssh -f $SSH_OPTS $ROBOT_USER@$ROBOT_IP"

# ── Step 3. 로봇 bringup 기동 ──────────────────────────────
# ROS_STATIC_PEERS 미설정 — SUBNET 범위로 같은 도메인(22)의 모든 노트북 자동 발견.
# 노트북 측에서만 ROS_STATIC_PEERS=192.168.0.138(RPi 고정 IP) 설정해서 unicast 개시.
echo " [INFO] 로봇 bringup 상태 확인..."
NEED_BRINGUP=0
if $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null"; then
    echo " [OK]  bringup 실행 중"
else
    NEED_BRINGUP=1
fi
if [ "$NEED_BRINGUP" = "1" ]; then
    echo " [INFO] bringup 기동 (ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID)..."
    $RSSH_F "mkdir -p ~/logs && setsid nohup bash -c 'export ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID; export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET; export RMW_IMPLEMENTATION=rmw_fastrtps_cpp; unset FASTRTPS_DEFAULT_PROFILES_FILE; unset ROS_STATIC_PEERS; source /opt/ros/jazzy/setup.bash; source ~/vicpinky_ws/install/setup.bash; exec ros2 launch vicpinky_bringup bringup.launch.xml' </dev/null >~/logs/bringup.log 2>&1 &"
    sleep 10
    if ! $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null"; then
        echo " [ERROR] bringup 기동 실패 — 원격 로그:"
        $RSSH 'tail -40 ~/logs/bringup.log'
        exit 1
    fi
    echo " [OK]  bringup 기동 완료"
fi

# ── Step 4. usb_cam 기동 (없을 때) ────────────────────────
# SKIP_CAM=1 이면 usb_cam 단계 전체 skip (W4.5 이전 — RPi에 USB 캠 미연결 상태)
if [ "${SKIP_CAM:-0}" = "1" ]; then
    echo " [INFO] usb_cam SKIP (SKIP_CAM=1) — UI 영상 패널은 빈 상태로 동작"
else
    echo " [INFO] usb_cam 상태 확인..."
    if $RSSH "pgrep -f '[u]sb_cam_node' >/dev/null"; then
        echo " [OK]  usb_cam 실행 중"
    else
        # ── Step 4a. HCAM01N 자동 검출 ──────────────────────
        # RPi 부팅/USB replug 마다 video index (0/2/...) 와 USB sysfs 경로 (1-2 / 4-1 ...)
        # 가 흔들려서 하드코딩이 깨지는 사고가 반복됨 (2026-05-07).
        # → v4l2 Card type 으로 디바이스 찾고, 그 디바이스의 USB sysfs 도 자동 산출.
        if [ -z "$CAM_DEV" ]; then
            echo " [INFO] HCAM01N 자동 검출..."
            DETECT_OUT=$(
                $RSSH 'bash -s' <<'REMOTE_DETECT_EOF'
set -u
for v in /dev/video*; do
  [ -e "$v" ] || continue
  name=$(v4l2-ctl -d "$v" --info 2>/dev/null | awk -F': *' '/Card type/ {print $2; exit}')
  case "$name" in
    *HCAM01N*)
      base=$(basename "$v")
      sysfs=$(readlink -f "/sys/class/video4linux/$base/device" 2>/dev/null)
      [ -n "$sysfs" ] || continue
      # sysfs 끝이 USB interface (예: 1-2:1.0). ":1.0" 떼면 USB device dir (1-2).
      iface=$(basename "$sysfs")
      usb_dev=${iface%:*}
      echo "$v|/sys/bus/usb/devices/$usb_dev/power/control"
      exit 0
      ;;
  esac
done
exit 1
REMOTE_DETECT_EOF
            )
            if [ -z "$DETECT_OUT" ]; then
                echo " [ERROR] HCAM01N 미검출 — RPi USB 카메라 연결 확인"
                echo "         힌트: SKIP_CAM=1 bash run_teleop_ui.sh  로 카메라 없이 시동"
                exit 1
            fi
            CAM_DEV="${DETECT_OUT%|*}"
            CAM_USB_CTRL="${DETECT_OUT##*|}"
            echo " [OK]  HCAM01N → $CAM_DEV  (USB: $CAM_USB_CTRL)"
        else
            CAM_USB_CTRL=""
            echo " [INFO] CAM_DEV 환경변수 명시: $CAM_DEV (auto-detect skip)"
        fi

        # ── Step 4b. USB auto-suspend 해제 ──────────────────
        # auto-suspend 상태에서 v4l2 stream open 시 format query 실패 → "unsupported"
        # 또는 "Select timeout" 즉사. 'on' 으로 강제하면 안전.
        if [ -n "$CAM_USB_CTRL" ]; then
            SUSPEND_RESULT=$($RSSH "
                if [ -w '$CAM_USB_CTRL' ]; then
                    echo on > '$CAM_USB_CTRL' && echo 'on (no sudo)'
                else
                    echo '$ROBOT_PASS' | sudo -S sh -c 'echo on > $CAM_USB_CTRL' 2>/dev/null && echo 'on (sudo)'
                fi" 2>&1 | tail -1)
            echo " [OK]  USB auto-suspend 해제: $SUSPEND_RESULT"
        fi

        # ── Step 4c. usb_cam_node 기동 ───────────────────────
        echo " [INFO] usb_cam 기동 ($CAM_DEV ${CAM_W}x${CAM_H}@${CAM_FPS})..."
        # HCAM01N (Microdia) 은 MJPG 미지원 — YUYV 만 가능. mjpeg2rgb 면 즉사.
        $RSSH_F "mkdir -p ~/logs && setsid nohup bash -c 'export ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID; export ROS_STATIC_PEERS=$LAPTOP_IP; export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET; source /opt/ros/jazzy/setup.bash; exec ros2 run usb_cam usb_cam_node_exe --ros-args -p video_device:=$CAM_DEV -p pixel_format:=yuyv2rgb -p image_width:=$CAM_W -p image_height:=$CAM_H -p framerate:=${CAM_FPS}.0 -p camera_name:=vic_pinky_cam -p frame_id:=camera_link' </dev/null >~/logs/usb_cam.log 2>&1 &"
        sleep 5
        if ! $RSSH "pgrep -f '[u]sb_cam_node' >/dev/null"; then
            echo " [ERROR] usb_cam 기동 실패 — 원격 로그:"
            $RSSH 'tail -40 ~/logs/usb_cam.log'
            echo " [HINT] USB 캠 미연결이면  SKIP_CAM=1 bash run_teleop_ui.sh  로 우회"
            exit 1
        fi
        echo " [OK]  usb_cam 기동 완료"
    fi
fi

# ── Step 4d. 노트북 dev_all (mode_manager + always-on 노드) 백그라운드 spawn ─
# 2026-05-09 Phase B: operator UI 의 follow/serving/npc 모드 전환 활성화.
# mode_manager 가 SetMode 서비스 처리 + 모드 별 stack spawn/kill.
echo " [INFO] dev_all (mode_manager + always-on 노드) 상태 확인..."
if pgrep -f '[d]ev_all.launch\|[m]ode_manager_node' >/dev/null; then
    echo " [OK]  dev_all 실행 중"
else
    echo " [INFO] dev_all 백그라운드 spawn..."
    mkdir -p ~/logs
    setsid nohup bash -c "
        export ROS_DOMAIN_ID=$ROS_DOMAIN_ID
        export ROS_STATIC_PEERS=$ROS_STATIC_PEERS
        export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
        export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
        unset FASTRTPS_DEFAULT_PROFILES_FILE
        source /opt/ros/jazzy/setup.bash
        source $WS/install/setup.bash
        exec ros2 launch dobi_npc_bringup dev_all.launch.py
    " </dev/null >~/logs/dev_all.log 2>&1 &
    sleep 5
    if ! pgrep -f '[m]ode_manager' >/dev/null; then
        echo " [WARN] mode_manager 미확인 — ~/logs/dev_all.log 확인"
        tail -20 ~/logs/dev_all.log
    else
        echo " [OK]  mode_manager 기동 (~/logs/dev_all.log)"
    fi
fi

# ── Step 5. 토픽 수신 확인 ────────────────────────────────
echo " [INFO] 토픽 수신 대기..."
ros2 daemon stop >/dev/null 2>&1
ros2 daemon start >/dev/null 2>&1
ODOM_OK=0; CAM_OK=0
for i in 1 2 3 4 5 6 7 8; do
    TL=$(ros2 topic list 2>/dev/null)
    [ $ODOM_OK -eq 0 ] && echo "$TL" | grep -qE "^/odom$" && ODOM_OK=1 && echo " [OK]  /odom"
    [ $CAM_OK -eq 0 ]  && echo "$TL" | grep -qE "^/image_raw/compressed$" && CAM_OK=1 && echo " [OK]  /image_raw/compressed"
    [ $ODOM_OK -eq 1 ] && [ $CAM_OK -eq 1 ] && break
    sleep 1
done
[ $ODOM_OK -eq 0 ] && echo " [WARN] /odom 미확인 (계속 진행)"
[ $CAM_OK  -eq 0 ] && echo " [WARN] /image_raw/compressed 미확인 (계속 진행)"

# ── Step 6. UI 서버 실행 (포그라운드) ─────────────────────
echo "------------------------------------------------------"
echo " 브라우저에서 열기:  http://localhost:$PORT"
echo " (또는 외부 접속:  http://<this-ip>:$PORT)"
echo " Ctrl+C 로 서버 종료"
echo "======================================================"

cd "$WS"
exec "$VENV/bin/python3" web/teleop_server.py
