#!/bin/bash
# ============================================================
# stop_teleop_ui.sh — vic_pinky teleop UI 종료
# 실행: bash stop_teleop_ui.sh         (UI + 원격 usb_cam 만 종료)
#       bash stop_teleop_ui.sh --all   (위 + 원격 vicpinky_bringup 도 종료)
# ============================================================

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"
PORT="${PORT:-8765}"

STOP_BRINGUP=0
[ "$1" = "--all" ] && STOP_BRINGUP=1

echo "======================================================"
echo " vic_pinky Teleop UI 종료"
echo "======================================================"

# ── 1) 로컬 프로세스 종료 ─────────────────────────────────
LOCAL_TARGETS=(
    "teleop_server.py"
    "run_teleop_ui.sh"
    "dev_all.launch.py"
    "dev_common.launch.py"
    "mode_manager"
    "follow_controller"
    "person_detector"
)
echo " [1] 로컬 프로세스 종료..."
for t in "${LOCAL_TARGETS[@]}"; do
    # pgrep self-match 방지: char class
    pat="[${t:0:1}]${t:1}"
    cnt=$(pgrep -fc "$pat" 2>/dev/null || echo 0)
    if [ "$cnt" -gt 0 ]; then
        echo "     kill: $t ($cnt 개)"
        pkill -9 -f "$pat" 2>/dev/null
    fi
done

sleep 1

# 포트 점유 정리
PORT_PID=$(lsof -ti:$PORT 2>/dev/null)
if [ -n "$PORT_PID" ]; then
    echo "     포트 $PORT 점유 PID=$PORT_PID 종료"
    kill -9 $PORT_PID 2>/dev/null
fi

# ── 2) 원격(로봇) 프로세스 종료 ──────────────────────────
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=4"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"

if ! command -v sshpass >/dev/null; then
    echo " [WARN] sshpass 미설치 — 원격 종료 스킵"
elif ! ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1; then
    echo " [WARN] 로봇($ROBOT_IP) 응답 없음 — 원격 종료 스킵"
else
    echo " [2] 원격 usb_cam 종료..."
    $RSSH "pkill -9 -f '[u]sb_cam_node' && echo '     usb_cam OK' || echo '     (없음)'"

    if [ $STOP_BRINGUP -eq 1 ]; then
        echo " [3] 원격 vicpinky_bringup 종료 (--all)..."
        $RSSH "pkill -9 -f '[v]icpinky_bringup'; pkill -9 -f '[r]os2 launch vicpinky'; pkill -9 -f '[s]llidar'; pkill -9 -f '[s]can_to_scan_filter'; echo '     bringup 관련 OK'"
    else
        echo " [3] vicpinky_bringup 유지 (--all 옵션으로 함께 종료 가능)"
    fi
fi

sleep 1

# ── 3) 결과 ──────────────────────────────────────────────
echo ""
echo " [4] 남은 프로세스 확인..."
local_left=$(pgrep -af 'teleop_server.py|run_teleop_ui.sh' 2>/dev/null | grep -v 'pgrep -af' | grep -v 'stop_teleop_ui.sh')
port_left=$(lsof -ti:$PORT 2>/dev/null)
if [ -z "$local_left" ] && [ -z "$port_left" ]; then
    echo "     로컬: 깨끗"
else
    [ -n "$local_left" ] && echo "     로컬 잔존: $local_left"
    [ -n "$port_left" ]  && echo "     포트 $PORT 점유: $port_left"
fi

echo ""
echo "======================================================"
echo " 재시작: bash run_teleop_ui.sh"
echo "======================================================"
