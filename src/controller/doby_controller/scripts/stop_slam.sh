#!/bin/bash
# ============================================================
# stop_slam.sh — vic_pinky SLAM (slam_toolbox + rviz) 정지
# 실행: bash stop_slam.sh
# 동작: 로컬 SLAM/rviz 관련 프로세스만 정지 (bringup, teleop UI 는 유지)
# 비고: teleop UI 의 SLAM STOP 버튼이 작동하지 않을 때, 또는 UI 없이
#       run_slam.sh 로 띄운 SLAM 을 정리할 때 사용.
# ============================================================

echo "======================================================"
echo " vic_pinky SLAM 정지"
echo "======================================================"

# 종료 대상 패턴 (pgrep self-match 방지: char class)
TARGETS=(
    "[r]os2 launch vicpinky_navigation map_building"
    "[r]os2 launch vicpinky_navigation map_view"
    "[s]ync_slam_toolbox_node"
    "[a]sync_slam_toolbox_node"
    "[s]lam_toolbox"
    "[r]viz2"
    "[r]un_slam.sh"
)

# ── 1) SIGTERM ───────────────────────────────────────────
echo " [1] SIGTERM..."
any=0
for pat in "${TARGETS[@]}"; do
    label="${pat//[\[\]]/}"
    cnt=$(pgrep -fc "$pat" 2>/dev/null || echo 0)
    if [ "$cnt" -gt 0 ]; then
        echo "     term: $label ($cnt 개)"
        pkill -TERM -f "$pat" 2>/dev/null
        any=1
    fi
done
[ $any -eq 0 ] && echo "     (해당 프로세스 없음)"

sleep 2

# ── 2) SIGKILL (남아 있으면) ─────────────────────────────
echo " [2] 잔존 확인 → SIGKILL..."
any=0
for pat in "${TARGETS[@]}"; do
    label="${pat//[\[\]]/}"
    cnt=$(pgrep -fc "$pat" 2>/dev/null || echo 0)
    if [ "$cnt" -gt 0 ]; then
        echo "     kill: $label ($cnt 개)"
        pkill -9 -f "$pat" 2>/dev/null
        any=1
    fi
done
[ $any -eq 0 ] && echo "     깨끗"

sleep 1

# ── 3) 결과 ──────────────────────────────────────────────
echo ""
echo " [3] 남은 프로세스 확인..."
left=$(pgrep -af 'slam_toolbox|vicpinky_navigation map_|rviz2|run_slam.sh' 2>/dev/null \
       | grep -v 'pgrep -af' | grep -v 'stop_slam.sh')
if [ -z "$left" ]; then
    echo "     SLAM/rviz: 깨끗"
else
    echo "     잔존:"
    echo "$left" | sed 's/^/       /'
fi

echo ""
echo "======================================================"
echo " teleop UI 와 bringup 은 유지됨."
echo " 재시작:  bash run_slam.sh   또는 UI(http://localhost:8765) 의 SLAM START"
echo "======================================================"
