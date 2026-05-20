#!/bin/bash
# ============================================================
# stop_robot_cam.sh — vic_pinky RPi v4l2_camera_node 종료 (moca 용)
# 실행:
#   bash stop_robot_cam.sh         원격 v4l2_camera_node 종료
#   bash stop_robot_cam.sh --keep  원격 유지, 로컬 ros2 daemon만 정리
# ============================================================

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"

KEEP=0
[ "$1" = "--keep" ] && KEEP=1

echo "======================================================"
echo " vic_pinky robot_cam 종료 (moca)"
echo "======================================================"

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=4"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"

# ── 1) 원격 종료 (또는 스킵) ─────────────────────────────
if [ $KEEP -eq 1 ]; then
    echo " [INFO] --keep 옵션 — 원격 v4l2_camera_node 유지"
elif ! command -v sshpass >/dev/null; then
    echo " [WARN] sshpass 미설치 — 원격 종료 스킵"
elif ! ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1; then
    echo " [WARN] 로봇($ROBOT_IP) 응답 없음 — 원격 종료 스킵"
else
    echo " [1] 원격 v4l2_camera_node 종료 (SIGINT → 2초 후 SIGKILL)..."
    $RSSH "
      pkill -INT -f '[v]4l2_camera_node' 2>/dev/null
      sleep 2
      pkill -KILL -f '[v]4l2_camera_node' 2>/dev/null
      if pgrep -f '[v]4l2_camera_node' >/dev/null; then
        echo '     [WARN] 잔존 프로세스 있음'
      else
        echo '     v4l2_camera_node 종료 OK'
      fi
    "
fi

# ── 2) 로컬 ros2 daemon 정리 ─────────────────────────────
echo " [2] 로컬 ros2 daemon 재기동..."
ros2 daemon stop >/dev/null 2>&1
echo "     (다음 ros2 명령에서 자동 재기동됨)"

echo "======================================================"
echo " 재시작: bash $(dirname "$0")/run_robot_cam.sh"
echo "======================================================"
