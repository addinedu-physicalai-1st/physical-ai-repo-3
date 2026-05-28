#!/bin/bash
# ============================================================
# run_nav2.sh — vic_pinky 자율주행 일괄 기동 (SmacPlanner2D + MPPI)
# 실행:  bash ~/moca/scripts/run_nav2.sh
# 동작:
#   1) 좀비(teleop_server, 이전 nav2, rviz) 정리 + ros2 daemon 재시작
#   2) RPi bringup 점검 — env(ROS_STATIC_PEERS=노트북IP) 맞는지 확인,
#      틀리거나 없으면 재기동 (Wi-Fi multicast 우회 unicast)
#   3) 토픽(/scan_filtered, /odom) 수신 대기
#   4) Nav2 (SmacPlanner2D+MPPI) 백그라운드 launch → <ws>/logs/nav2.log
#   5) AMCL active 대기 후 RViz 포그라운드 실행
#   6) 백그라운드 watcher가 map→odom TF 감지 시 lifecycle 강제 활성화
#      (사용자가 RViz에서 60s 안에 pose 못 찍어도 abort 회피)
#   7) RViz 종료(또는 Ctrl+C) 시 Nav2 정리, RPi bringup은 유지
# 환경변수 override:
#   ROBOT_IP=192.168.0.138, ROBOT_USER=vic, ROBOT_PASS=1
#   ROS_DOMAIN_ID=22, MAP=mapv6.yaml
# ============================================================

set -u

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"
DOMAIN="${ROS_DOMAIN_ID:-22}"
MAP="${MAP:-mapv6.yaml}"

# 스크립트 자기 위치 기준으로 워크스페이스 경로 결정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$WS_DIR/logs"
mkdir -p "$LOG_DIR"

# ── ROS env (노트북 측) ─────────────────────────────────────
export ROS_DOMAIN_ID=$DOMAIN
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE 2>/dev/null || true
export ROS_STATIC_PEERS="$ROBOT_IP"
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
LAPTOP_IP=$(hostname -I | awk '{print $1}')

set +u
source /opt/ros/jazzy/setup.bash
if [ -f "$WS_DIR/install/setup.bash" ]; then
    source "$WS_DIR/install/setup.bash"
else
    set -u
    echo " [ERR] $WS_DIR/install/setup.bash 없음 — 'colcon build' 먼저"; exit 1
fi
set -u

echo "=========================================="
echo " vic_pinky Nav2 자율주행 기동"
echo "  Robot     : $ROBOT_USER@$ROBOT_IP"
echo "  Laptop    : $LAPTOP_IP"
echo "  Domain    : $DOMAIN"
echo "  Map       : $MAP"
echo "  Log dir   : $LOG_DIR"
echo "=========================================="

# ── 사전 점검 ───────────────────────────────────────────────
ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1 || { echo " [ERR] RPi ping 실패"; exit 1; }
command -v sshpass >/dev/null || { echo " [ERR] sshpass 미설치 — 'sudo apt install sshpass'"; exit 1; }

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"

# ── 시계 drift 검사 ────────────────────────────────────────
# 100ms+ 어긋나면 AMCL/costmap이 scan timestamp를 미래/과거로 보고 drop —
# nav2.log의 "Message Filter dropping ... laser_link" 폭주 원인.
T1=$(date +%s%N)
T_REMOTE=$($RSSH "date +%s%N" 2>/dev/null)
T2=$(date +%s%N)
if [ -n "$T_REMOTE" ]; then
    # SSH round-trip 절반을 빼고 비교 (ms 단위)
    DRIFT_MS=$(( (T_REMOTE - (T1 + T2) / 2) / 1000000 ))
    ABS_DRIFT=${DRIFT_MS#-}
    if [ "$ABS_DRIFT" -gt 100 ]; then
        echo " [WARN] 시계 drift: RPi가 노트북 대비 ${DRIFT_MS} ms — Nav2가 scan 떨굴 수 있음"
        echo "        해결 시도 중..."
        # RPi: 비밀번호 알고 있으니 자동 sync
        $RSSH "echo $ROBOT_PASS | sudo -S systemctl restart systemd-timesyncd" 2>/dev/null && \
            echo "        → RPi timesyncd 재시작 완료"
        # 노트북: sudo 비번 모르니 사용자에게 위임 (대화형이라 안전)
        if sudo -n systemctl restart systemd-timesyncd 2>/dev/null; then
            echo "        → laptop timesyncd 재시작 완료 (sudo nopasswd)"
        else
            echo "        → laptop 은 수동 실행 필요: sudo systemctl restart systemd-timesyncd"
        fi
        # 재측정
        sleep 2
        T1=$(date +%s%N); T_REMOTE=$($RSSH "date +%s%N" 2>/dev/null); T2=$(date +%s%N)
        DRIFT_MS=$(( (T_REMOTE - (T1 + T2) / 2) / 1000000 ))
        ABS_DRIFT=${DRIFT_MS#-}
        if [ "$ABS_DRIFT" -gt 100 ]; then
            echo " [WARN] 재측정 후 drift ${DRIFT_MS} ms — 여전히 큼. nav2.log TF 에러 무시 가능하나 localization 정확도 저하."
        else
            echo " [OK]  재측정 drift ${DRIFT_MS} ms"
        fi
    else
        echo " [OK]  시계 drift ${DRIFT_MS} ms (laptop ↔ RPi)"
    fi
else
    echo " [WARN] RPi 시각 측정 실패 — drift 검사 생략"
fi

# ── 1) 좀비 정리 ───────────────────────────────────────────
echo " [1/6] 좀비 정리..."
pkill -9 -f "web/teleop_server.py" 2>/dev/null || true
pkill -9 -f "ros2 launch vicpinky_navigation" 2>/dev/null || true
pkill -9 -f "nav2_container" 2>/dev/null || true
pkill -9 -f "rviz2" 2>/dev/null || true
sleep 1
ros2 daemon stop >/dev/null 2>&1 || true
sleep 1

# ── 2) RPi bringup 점검/재기동 ─────────────────────────────
echo " [2/6] RPi bringup 점검..."
NEED_RESTART=0
if $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null" 2>/dev/null; then
    # env 검사 — launch 프로세스의 ROS_STATIC_PEERS가 laptop_ip 가리키는지.
    # 외곽 bash -c 는 export 전 환경이라 ROS_STATIC_PEERS 없음 → inner python3 ros2 launch 만 매칭해야 false-mismatch 회피.
    if ! $RSSH "PID=\$(pgrep -f 'python3 .*ros2 launch vicpinky_bringup' | head -1); [ -n \"\$PID\" ] && tr '\0' '\n' </proc/\$PID/environ | grep -q 'ROS_STATIC_PEERS=$LAPTOP_IP'"; then
        echo "      → bringup 살아있지만 env 잘못됨 (ROS_STATIC_PEERS 미설정/다른 IP), 재기동"
        NEED_RESTART=1
    else
        echo "      → bringup OK (ROS_STATIC_PEERS=$LAPTOP_IP)"
    fi
else
    echo "      → bringup 없음, 신규 기동"
    NEED_RESTART=1
fi

if [ $NEED_RESTART -eq 1 ]; then
    $RSSH "pkill -9 -f 'ros2 launch vicpinky_bringup' 2>/dev/null; pkill -9 -f vicpinky_bringup 2>/dev/null; pkill -9 -f sllidar 2>/dev/null; pkill -9 -f scan_to_scan_filter_chain 2>/dev/null; sleep 2"
    $RSSH "mkdir -p ~/logs && setsid nohup bash -c 'export ROS_DOMAIN_ID=$DOMAIN; export ROS_STATIC_PEERS=$LAPTOP_IP; export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET; source /opt/ros/jazzy/setup.bash; source ~/vicpinky_ws/install/setup.bash; exec ros2 launch vicpinky_bringup bringup.launch.xml' </dev/null >~/logs/bringup.log 2>&1 &"
    echo "      → 기동 중, 10s 대기..."
    sleep 10
    if ! $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null" 2>/dev/null; then
        echo " [ERR] RPi bringup 기동 실패. 원격 로그:"
        $RSSH 'tail -40 ~/logs/bringup.log'
        exit 1
    fi
    echo "      → OK"
fi

# ── 3) ros2 daemon + 토픽 수신 대기 ────────────────────────
echo " [3/6] ros2 daemon 재시작 + 토픽 확인..."
ros2 daemon start >/dev/null 2>&1
sleep 3
TOPIC_OK=0
for i in {1..12}; do
    if ros2 topic list 2>/dev/null | grep -q "^/scan_filtered$"; then
        TOPIC_OK=1; break
    fi
    sleep 1
done
if [ $TOPIC_OK -eq 0 ]; then
    echo " [ERR] /scan_filtered 미수신. 네트워크/RPi env 점검 필요"
    echo "      → 디버그: ros2 topic list, ssh로 RPi 직접 확인"
    exit 1
fi
echo "      → /scan_filtered OK"

# ── 4) Nav2 백그라운드 launch ──────────────────────────────
echo " [4/6] Nav2 (SmacPlanner2D + MPPI) 기동..."
MAP_PATH="$(ros2 pkg prefix moca_navigation)/share/moca_navigation/map/$MAP"
if [ ! -f "$MAP_PATH" ]; then
    echo " [ERR] 맵 파일 없음: $MAP_PATH"
    echo "      → MAP=<filename> 환경변수로 변경 가능 (예: MAP=mapv6.yaml)"
    exit 1
fi
ros2 launch moca_navigation bringup_smac_mppi.launch.xml \
    map:="$MAP_PATH" \
    > "$LOG_DIR/nav2.log" 2>&1 &
NAV2_PID=$!
echo "      → PID $NAV2_PID, log: $LOG_DIR/nav2.log"

# ── 5) AMCL/map_server active 대기 ─────────────────────────
echo " [5/6] localization 활성 대기 (최대 30s)..."
for i in {1..30}; do
    if ros2 lifecycle get /amcl 2>/dev/null | grep -q active; then
        echo "      → AMCL active"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo " [WARN] AMCL active 안 됨. Nav2 로그 확인: tail -50 $LOG_DIR/nav2.log"
    fi
done

# 백그라운드 watcher — 사용자가 RViz에서 pose 찍으면 lifecycle 강제 활성화
(
    # AMCL이 map→odom TF 발행하는지 폴링
    for i in {1..300}; do
        if timeout 2 ros2 run tf2_ros tf2_echo map odom 2>&1 | grep -q "Translation"; then
            sleep 2
            for n in /controller_server /planner_server /bt_navigator /behavior_server /waypoint_follower; do
                ros2 lifecycle set $n activate >/dev/null 2>&1 || true
            done
            echo " [WATCH] Lifecycle 활성화 완료 — RViz에서 Nav2 Goal 보내봐."
            break
        fi
        sleep 2
    done
) &
WATCH_PID=$!

# ── 6) RViz 포그라운드 ─────────────────────────────────────
echo " [6/6] RViz 실행..."
echo "=========================================="
echo " ★ RViz에서 즉시 '2D Pose Estimate' 클릭 → 로봇 실위치 클릭+드래그"
echo " ★ localization 완료되면 'Nav2 Goal' 클릭 → 목적지 클릭+드래그"
echo " ★ 종료: 이 터미널 Ctrl+C 또는 RViz 창 닫기"
echo "=========================================="

# trap — Ctrl+C 또는 RViz 종료 시 nav2/watcher 정리, RPi bringup은 유지
cleanup() {
    echo ""
    echo " [종료] 정리 중..."
    kill $WATCH_PID 2>/dev/null || true
    kill -9 $NAV2_PID 2>/dev/null || true
    pkill -9 -f "nav2_container" 2>/dev/null || true
    pkill -9 -f "rviz2" 2>/dev/null || true
    echo " [종료] Nav2 + RViz 정리 완료. RPi bringup은 유지 (수동 종료 필요)."
    exit 0
}
trap cleanup INT TERM EXIT

ros2 launch nav2_bringup rviz_launch.py 2>&1 | tee "$LOG_DIR/rviz.log"
