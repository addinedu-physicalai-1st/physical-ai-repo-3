#!/bin/bash
# ============================================================
# run_sim.sh — Gazebo 시뮬 풀 스택 + 운영 UI 한 줄 기동
#
# 사용:
#   bash <repo>/scripts/run_sim.sh             # 전체 (Gazebo + Nav2 + RViz + UI)
#   bash <repo>/scripts/run_sim.sh --no-rviz   # RViz 제외
#   bash <repo>/scripts/run_sim.sh --no-nav2   # Gazebo 만 (UI 검증 위한 최소)
#   bash <repo>/scripts/run_sim.sh --cleanup   # 좀비 정리 후 기동
#   bash <repo>/scripts/run_sim.sh --test-mode # opserver MOCA_TEST_MODE=1 (시나리오 자동)
#
# 환경: ROS_DOMAIN_ID=99 + ROS_LOCALHOST_ONLY=1 (시뮬 전용, §0-A 정합)
#
# 구성:
#   0. (옵션 --cleanup) 풀 스택 사전 정리 — stop_sim.sh 위임
#      ★ Step 1 보다 먼저 실행. stop_moca.sh 패턴이 'ros2 launch' 매칭이라
#        Step 1 이후 호출하면 방금 띄운 Gazebo+Nav2 도 같이 죽음.
#   1. Gazebo + Nav2 (+ RViz) — run_nav2_sim.sh 위임
#   2. 운영 UI (mode_manager + opserver_node) — run_dashboard.sh --domain=99
#   3. 브라우저 자동 open (http://localhost:8800/)
#
# 종료:
#   bash <repo>/scripts/stop_sim.sh
# ============================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAV2_OPT=""
DASH_TEST_OPT=""
NO_NAV2=0
CLEANUP=0
for arg in "$@"; do
    case "$arg" in
        --no-rviz)    NAV2_OPT="--no-rviz" ;;
        --no-nav2)    NO_NAV2=1 ;;
        --cleanup)    CLEANUP=1 ;;
        --test-mode)  DASH_TEST_OPT="--test-mode" ;;
        -h|--help)
            sed -n '2,/^# =====*$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
    esac
done

log() { echo "[run_sim] $*"; }

if [ "$CLEANUP" = 1 ]; then
    log "Step 0/3 — 풀 스택 사전 정리 (stop_sim.sh)"
    bash "$SCRIPT_DIR/stop_sim.sh" >/dev/null 2>&1 || true
    echo ""
fi

log "Step 1/3 — Gazebo 시뮬 풀 스택"
if [ "$NO_NAV2" = 1 ]; then
    log "  (--no-nav2) Gazebo + Nav2 skip — UI 단독 검증 모드"
else
    if ! bash "$SCRIPT_DIR/run_nav2_sim.sh" $NAV2_OPT; then
        log "Step 1 실패 — Gazebo/Nav2가 기동되지 않아 중단합니다."
        log "  로그와 맵 자산을 확인하세요: $SCRIPT_DIR/../maps/mapv5_mocamap.yaml"
        exit 1
    fi
fi

echo ""
log "Step 2/3 — 운영 UI (DOMAIN=99 시뮬)"
# ★ run_dashboard.sh 의 --cleanup 은 stop_moca.sh ('ros2 launch' 매칭) 호출 →
#   방금 띄운 Gazebo+Nav2 launch 가 같이 죽음. run_sim 흐름에선 절대 forward X.
if ! bash "$SCRIPT_DIR/run_dashboard.sh" --domain=99 --no-browser $DASH_TEST_OPT; then
    log "Step 2 실패 — 운영 UI 기동 실패."
    exit 1
fi

echo ""
log "Step 3/3 — 브라우저 open"
URL="http://localhost:8800/"
for cmd in xdg-open sensible-browser google-chrome chromium firefox; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ("$cmd" "$URL" >/dev/null 2>&1 &)
        log "브라우저 자동 open ($cmd): $URL"
        break
    fi
done

echo ""
log "✓ 시뮬 풀 스택 + 운영 UI 기동 완료"
log "  Gazebo: gz sim (DOMAIN=99)"
log "  운영 UI: $URL"
log "  종료: bash $SCRIPT_DIR/stop_sim.sh"
