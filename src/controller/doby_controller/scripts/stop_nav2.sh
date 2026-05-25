#!/bin/bash
# ============================================================
# stop_nav2.sh — run_nav2.sh 가 띄운 Nav2 + RViz 정리
# 실행:
#   bash stop_nav2.sh                  로컬 nav2/rviz/watcher 만 정리 (기본)
#   bash stop_nav2.sh --with-bringup   RPi vicpinky_bringup 도 함께 종료
# 비고: run_nav2.sh 의 trap cleanup 이 안 돈 경우 (강제 kill, 셸 닫힘) 사용.
# ============================================================

WITH_BRINGUP=0
[ "$1" = "--with-bringup" ] && WITH_BRINGUP=1

echo "======================================================"
echo " run_nav2 정리"
echo "======================================================"

# 종료 대상 패턴 (pgrep self-match 방지: char class)
TARGETS=(
    "[r]os2 launch vicpinky_navigation bringup_smachybrid"
    "[r]os2 launch nav2_bringup rviz_launch"
    # 더 specific 패턴 — 부모 셸/grep 인자에 노출돼도 매치 안 되게 cmdline 특성 문자열 사용
    "__node:=nav2_container"
    "nav2_default_view.rviz"
    "[t]f2_echo map odom"
    "/run_nav2.sh"
)

# ── 1) SIGTERM ───────────────────────────────────────────
echo " [1] SIGTERM..."
any=0
for pat in "${TARGETS[@]}"; do
    label="${pat//[\[\]]/}"
    cnt=$(pgrep -fc "$pat" 2>/dev/null || true)
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
    cnt=$(pgrep -fc "$pat" 2>/dev/null || true)
    if [ "$cnt" -gt 0 ]; then
        echo "     kill: $label ($cnt 개)"
        pkill -9 -f "$pat" 2>/dev/null
        any=1
    fi
done
[ $any -eq 0 ] && echo "     깨끗"

sleep 1

# ── 3) 로컬 ros2 daemon 재기동 ───────────────────────────
echo " [3] 로컬 ros2 daemon 재기동..."
ros2 daemon stop >/dev/null 2>&1
echo "     (다음 ros2 명령에서 자동 재기동됨)"

# ── 4) (옵션) RPi bringup 종료 ───────────────────────────
if [ $WITH_BRINGUP -eq 1 ]; then
    echo ""
    echo " [4] RPi bringup 종료 (--with-bringup)..."
    if [ -x "$(dirname "$0")/stop_vic_bringup.sh" ]; then
        bash "$(dirname "$0")/stop_vic_bringup.sh"
    else
        echo "     [WARN] stop_vic_bringup.sh 못 찾음 — 수동 종료 필요"
    fi
fi

# ── 5) 결과 ──────────────────────────────────────────────
echo ""
echo " [확인] 남은 프로세스..."
left=$(pgrep -af 'vicpinky_navigation bringup_smachybrid|nav2_bringup rviz_launch|nav2_container|rviz2|tf2_echo map odom|run_nav2.sh' 2>/dev/null \
       | grep -v 'pgrep -af' | grep -v 'stop_nav2.sh')
if [ -z "$left" ]; then
    echo "     Nav2/RViz/watcher: 깨끗"
else
    echo "     잔존:"
    echo "$left" | sed 's/^/       /'
fi

echo ""
echo "======================================================"
if [ $WITH_BRINGUP -eq 0 ]; then
    echo " RPi bringup 은 유지됨. 함께 끄려면 --with-bringup 옵션."
fi
echo " 재시작:  bash $(dirname "$0")/run_nav2.sh"
echo "======================================================"
