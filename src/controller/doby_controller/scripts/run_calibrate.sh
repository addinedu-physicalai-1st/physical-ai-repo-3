#!/bin/bash
# ============================================================
# run_calibrate.sh — vic_pinky 주행 캘리브레이션 (S3) 래퍼
# 실행 예:
#   bash run_calibrate.sh straight             # 1m 직진
#   bash run_calibrate.sh straight --dist 0.5  # 짧게 테스트
#   bash run_calibrate.sh rotate               # 360° 회전
#   bash run_calibrate.sh rotate --angle 90    # 90°만
#   bash run_calibrate.sh square               # 1m×1m 사각형
#   bash run_calibrate.sh stop                 # 비상 정지
#
# 동작:
#   1) ROS2 환경 + moca venv source
#   2) (선택) teleop UI 실행 중이면 경고 (cmd_vel 충돌)
#   3) 로봇 bringup 실행 중인지 확인
#   4) tools/calibrate_drive.py 실행
# ============================================================

# 스크립트 위치 기반 워크스페이스 루트 — clone 위치 무관 작동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$WS/.venv"

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"

export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
source /opt/ros/jazzy/setup.bash
[ -d "$VENV" ] || { echo " [ERROR] venv 없음: $VENV"; exit 1; }
source "$VENV/bin/activate"

# teleop UI 가 cmd_vel publishing 중이면 충돌 — 경고
if pgrep -f '[t]eleop_server.py' >/dev/null; then
    echo "⚠️  teleop UI 서버가 실행 중입니다 (cmd_vel 충돌 위험)."
    echo "    먼저 종료 권장:  bash $WS/scripts/stop_teleop_ui.sh"
    read -r -p "    그래도 진행? [y/N]: " ans
    [[ "$ans" =~ ^[yY]$ ]] || exit 1
fi

# bringup 확인
if command -v sshpass >/dev/null && ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1; then
    if ! sshpass -p "$ROBOT_PASS" ssh -o StrictHostKeyChecking=no -o LogLevel=ERROR \
            "$ROBOT_USER@$ROBOT_IP" "pgrep -f '[v]icpinky_bringup' >/dev/null"; then
        echo " [ERROR] 로봇 bringup 미실행. 먼저 bash run_teleop_ui.sh 또는 bringup 기동."
        exit 1
    fi
fi

cd "$WS"
exec python3 tools/calibrate_drive.py "$@"
