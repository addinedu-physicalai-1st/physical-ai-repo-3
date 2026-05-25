#!/bin/bash
# ============================================================
# stop_furniture_picker.sh — place_furniture_picker.py 강제 종료
#
# 증상: 창을 X 로 닫아도 python 프로세스가 살아있어 백그라운드에 잔존.
#       (Tk + PhotoImage 참조로 mainloop 종료 후에도 인터프리터가 안 빠짐)
#
# 실행:
#   bash stop_furniture_picker.sh        # SIGTERM → 2초 후 SIGKILL
#   bash stop_furniture_picker.sh -9     # 즉시 SIGKILL
# ============================================================

PATTERN='[p]lace_furniture_picker.py'
FORCE=0
[ "$1" = "-9" ] && FORCE=1

echo "======================================================"
echo " place_furniture_picker.py 종료"
echo "======================================================"

PIDS=$(pgrep -f "$PATTERN")
if [ -z "$PIDS" ]; then
    echo " [OK] 실행 중인 프로세스 없음"
    exit 0
fi

echo " [발견] PIDs: $PIDS"
ps -o pid,etime,cmd -p $PIDS 2>/dev/null

if [ $FORCE -eq 1 ]; then
    echo " [1] SIGKILL..."
    kill -KILL $PIDS 2>/dev/null
else
    echo " [1] SIGTERM..."
    kill -TERM $PIDS 2>/dev/null
    sleep 2
    LEFT=$(pgrep -f "$PATTERN")
    if [ -n "$LEFT" ]; then
        echo " [2] 잔존 — SIGKILL: $LEFT"
        kill -KILL $LEFT 2>/dev/null
    fi
fi

sleep 0.5
if pgrep -f "$PATTERN" >/dev/null; then
    echo " [FAIL] 여전히 잔존:"
    pgrep -af "$PATTERN"
    exit 1
fi
echo " [OK] 종료 완료"
