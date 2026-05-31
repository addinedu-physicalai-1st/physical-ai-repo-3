#!/bin/bash
# ============================================================
# run_sim.sh — Gazebo 시뮬 풀 스택 + ROS-only 운영층 한 줄 기동
#
# 사용:
#   bash <repo>/scripts/run_sim.sh             # 전체 (Gazebo + Nav2 + RViz + UI)
#   bash <repo>/scripts/run_sim.sh --no-rviz   # RViz 제외
#   bash <repo>/scripts/run_sim.sh --no-nav2   # Gazebo 만 (UI 검증 위한 최소)
#   bash <repo>/scripts/run_sim.sh --cleanup   # 좀비 정리 후 기동
#   bash <repo>/scripts/run_sim.sh --test-mode # legacy no-op
#
# 환경: ROS_DOMAIN_ID=99 + ROS_LOCALHOST_ONLY=1 (시뮬 전용, §0-A 정합)
#
# 구성:
#   0. (옵션 --cleanup) 풀 스택 사전 정리 — stop_sim.sh 위임
#      ★ Step 1 보다 먼저 실행. stop_moca.sh 패턴이 'ros2 launch' 매칭이라
#        Step 1 이후 호출하면 방금 띄운 Gazebo+Nav2 도 같이 죽음.
#   1. Gazebo + Nav2 (+ RViz) — run_nav2_sim.sh 위임 (run_sim 전용 mapv5 override)
#   2. ROS-only 운영층 (mode_manager + task_orchestrator) — run_dashboard.sh --domain=99
#   3. ROS service 확인
#
# 종료:
#   bash <repo>/scripts/stop_sim.sh
# ============================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_NAV2_MAP="$SCRIPT_DIR/../maps/mapv5_mocamap.yaml"

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
    if [ ! -f "$SIM_NAV2_MAP" ]; then
        log "Step 1 실패 — run_sim 전용 Nav2 mapv5 자산을 찾을 수 없습니다."
        log "  확인 경로: $SIM_NAV2_MAP"
        exit 1
    fi
    if ! bash "$SCRIPT_DIR/run_nav2_sim.sh" $NAV2_OPT --map="$SIM_NAV2_MAP"; then
        log "Step 1 실패 — Gazebo/Nav2가 기동되지 않아 중단합니다."
        log "  로그와 맵 자산을 확인하세요: $SIM_NAV2_MAP"
        exit 1
    fi
fi

echo ""
log "Step 2/3 — ROS-only 운영층 (DOMAIN=99 시뮬)"
# ★ run_dashboard.sh 의 --cleanup 은 stop_moca.sh ('ros2 launch' 매칭) 호출 →
#   방금 띄운 Gazebo+Nav2 launch 가 같이 죽음. run_sim 흐름에선 절대 forward X.
if ! bash "$SCRIPT_DIR/run_dashboard.sh" --domain=99 --no-browser $DASH_TEST_OPT; then
    log "Step 2 실패 — 운영 UI 기동 실패."
    exit 1
fi

echo ""
log "Step 3/3 — ROS service 확인"
ros2 service list | grep -E '^/(mode/request|task/request_serving|task/request_guiding)$' || true

echo ""
log "✓ 시뮬 풀 스택 + ROS-only 운영층 기동 완료"
log "  Gazebo: gz sim (DOMAIN=99)"
log "  운영 서비스: /mode/request, /task/request_serving, /task/request_guiding"
log "  종료: bash $SCRIPT_DIR/stop_sim.sh"
