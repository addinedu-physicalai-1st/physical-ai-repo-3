#!/bin/bash
# ============================================================
# run_operator_ui.sh — Dobi NPC 운영자 패널 (moca/web)
# 실행: bash run_operator_ui.sh
# 브라우저: http://localhost:8765/operator
# ------------------------------------------------------------
# 동작:
#   1) moca venv ($WS/.venv) activate
#   2) ROS 2 Jazzy + moca install/setup.bash source (dobi_npc_msgs 필요)
#   3) ROS_DOMAIN_ID=22 + fastrtps
#   4) FastAPI 서버 실행 (포그라운드, port 8765)
# ------------------------------------------------------------
# 전제:
#   - $WS/.venv 존재 (없으면: python3 -m venv --system-site-packages $WS/.venv
#                                  && $WS/.venv/bin/pip install fastapi uvicorn)
#   - $WS/install/setup.bash 존재 (colcon build 완료)
#   - dev_all.launch.py 가 별도 터미널에서 떠있어야 모드 전환/발화가 실 노드와 통신
# ------------------------------------------------------------
# 비고:
#   - 별도 텔레옵 UI 와 본 운영자 패널은 별개. 본 스크립트는 운영자 패널만 띄움.
#   - bringup/USB 캠 자동 기동 안 함. 필요 시 scripts/run_teleop_ui.sh 별도 사용.
# ============================================================

set -e

# 스크립트 위치 기반 워크스페이스 루트 — clone 위치 무관 작동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$WS/.venv"
PORT="${PORT:-8765}"

echo "======================================================"
echo " Dobi NPC 운영자 패널 (moca/web)"
echo "======================================================"

# Step 1. venv 점검
if [ ! -f "$VENV/bin/activate" ]; then
    echo " [ERROR] $VENV 없음 — 다음 명령으로 먼저 생성:"
    echo "   python3 -m venv --system-site-packages $VENV"
    echo "   $VENV/bin/pip install fastapi uvicorn"
    exit 1
fi

# Step 2. ROS 환경
export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
source /opt/ros/jazzy/setup.bash

if [ -f "$WS/install/setup.bash" ]; then
    source "$WS/install/setup.bash"
else
    echo " [WARN] $WS/install/setup.bash 없음 — dobi_npc_msgs import 실패 예상"
    echo "        먼저 'colcon build --symlink-install' 실행 권장"
fi

echo " WS            : $WS"
echo " ROS_DOMAIN_ID : $ROS_DOMAIN_ID"
echo " UI            : http://localhost:$PORT/operator"
echo "------------------------------------------------------"

# Step 3. venv activate + 서버 시동 (포그라운드)
source "$VENV/bin/activate"
cd "$WS"
exec python3 web/teleop_server.py
