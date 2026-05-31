#!/bin/bash
# ============================================================
# run_dashboard.sh — moca_opserver Web Dashboard 한 줄 기동
#
# 사용:
#   bash <repo>/scripts/run_dashboard.sh             # 기본 (브라우저 자동 open)
#   bash <repo>/scripts/run_dashboard.sh --cleanup   # 시작 전 좀비 정리
#   bash <repo>/scripts/run_dashboard.sh --no-browser
#   bash <repo>/scripts/run_dashboard.sh --verbose   # stdout 콘솔 직접
#   bash <repo>/scripts/run_dashboard.sh --port=9000 # 포트 변경
#   bash <repo>/scripts/run_dashboard.sh --domain=22 # 실물 (§0-A 해제 시점만)
#   bash <repo>/scripts/run_dashboard.sh --domain=99 # 시뮬 (default, Gazebo + PC 단독)
#   bash <repo>/scripts/run_dashboard.sh --test-mode # 시나리오 테스트용 — /api/v1/_test/* 활성
#
# 기동:
#   1. CLAUDE.md §0-A 정합 — DOMAIN 기본 99 + LOCALHOST_ONLY=1 (시뮬)
#      --domain=22 시 실물 모드 (LOCALHOST_ONLY=0 + §0-A 정책 검증 필요)
#   2. ROS jazzy + install/setup.bash source
#   3. mode_manager + opserver_node setsid 분리 spawn
#   4. 5초 대기 + curl /api/v1/health 검증
#   5. http://localhost:8800/ 브라우저 자동 open
#
# 종료:
#   bash <repo>/scripts/stop_moca.sh
# ============================================================

set -u

# 워크스페이스 추정 (CLAUDE.md §7 상대경로 컨벤션)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"

CLEANUP=0
NO_BROWSER=0
VERBOSE=0
PORT=8800
DOMAIN=99
TEST_MODE=0
for arg in "$@"; do
    case "$arg" in
        --cleanup)    CLEANUP=1 ;;
        --no-browser) NO_BROWSER=1 ;;
        --verbose)    VERBOSE=1 ;;
        --port=*)     PORT="${arg#*=}" ;;
        --domain=*)   DOMAIN="${arg#*=}" ;;
        --test-mode)  TEST_MODE=1 ;;
        -h|--help)
            sed -n '2,/^# =====*$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
    esac
done

log() { echo "[run_dashboard] $*"; }

# 환경 격리 — CLAUDE.md §0-A
# DOMAIN 22 (실물) vs 99 (시뮬). LOCALHOST_ONLY 는 시뮬에서만 1, 실물은 0 (LAN broadcast).
export ROS_DOMAIN_ID="$DOMAIN"
if [ "$DOMAIN" = "22" ]; then
    export ROS_LOCALHOST_ONLY=0
    export MOCA_DOMAIN_HINT="실물"
    log "★ DOMAIN=22 실물 모드 — §0-A 정책 (RPi 접근 정책) 사전 확인 필수"
else
    export ROS_LOCALHOST_ONLY=1
    export MOCA_DOMAIN_HINT="시뮬"
fi
if [ "$TEST_MODE" = 1 ]; then
    export MOCA_TEST_MODE=1
    log "★ TEST_MODE 활성 — /api/v1/_test/inject_state endpoint 등록 (운영 금지)"
fi

# ROS jazzy + workspace setup
if [ ! -f "/opt/ros/jazzy/setup.bash" ]; then
    log "★ /opt/ros/jazzy/setup.bash 없음 — ROS2 Jazzy 설치 확인" >&2
    exit 1
fi
if [ ! -f "$WS/install/setup.bash" ]; then
    log "★ $WS/install/setup.bash 없음 — 먼저 colcon build" >&2
    exit 1
fi

# 가상환경 (.doby) 자동 활성화
if [ -f "$WS/.doby/bin/activate" ]; then
    log "가상환경 활성화: .doby"
    # shellcheck source=/dev/null
    source "$WS/.doby/bin/activate"
fi
# ROS setup.bash 가 ${AMENT_TRACE_SETUP_FILES} 같은 unbound var 참조 → set -u 일시 해제.
set +u
# shellcheck source=/dev/null
source /opt/ros/jazzy/setup.bash
# shellcheck source=/dev/null
source "$WS/install/setup.bash"
set -u

# 좀비 cleanup (--cleanup) — source 이후 호출 → stop_moca 의 ros2 daemon reset/검증 작동
if [ "$CLEANUP" = 1 ]; then
    log "시작 전 좀비 정리 (stop_moca.sh)..."
    bash "$SCRIPT_DIR/stop_moca.sh" --quiet || true
    sleep 1
fi

# 로그 디렉토리 (workspace log/, .gitignore 안)
TS=$(date +%Y%m%d_%H%M%S)
LOG_DIR="$WS/log/dashboard_${TS}"
mkdir -p "$LOG_DIR"

log "ROS_DOMAIN_ID=$ROS_DOMAIN_ID  LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY  ($MOCA_DOMAIN_HINT)"
log "WS=$WS"
log "LOG=$LOG_DIR"
echo ""

# mode_manager
log "mode_manager 시작..."
if [ "$VERBOSE" = 1 ]; then
    setsid ros2 run dobi_npc_bringup mode_manager &
else
    setsid ros2 run dobi_npc_bringup mode_manager \
        >"$LOG_DIR/mode_manager.log" 2>&1 &
fi
sleep 1

# table_markers — RViz 에서 /serving/table_markers 로 테이블/정차 위치 표시
log "table_markers 시작..."
if [ "$VERBOSE" = 1 ]; then
    setsid ros2 run dobi_npc_bringup table_markers &
else
    setsid ros2 run dobi_npc_bringup table_markers \
        >"$LOG_DIR/table_markers.log" 2>&1 &
fi
sleep 1

# opserver_node
log "opserver_node 시작 (port $PORT)..."
if [ "$VERBOSE" = 1 ]; then
    setsid ros2 run moca_opserver opserver_node \
        --ros-args -p "port:=$PORT" &
else
    setsid ros2 run moca_opserver opserver_node \
        --ros-args -p "port:=$PORT" \
        >"$LOG_DIR/opserver_node.log" 2>&1 &
fi

# Health check
log "5초 대기 후 health check..."
sleep 5
URL="http://localhost:${PORT}"
if curl -fsS "${URL}/api/v1/health" >/dev/null 2>&1; then
    log "✓ opserver 응답 OK"
else
    log "★ opserver health check 실패 — 로그 확인:"
    log "  $LOG_DIR/opserver_node.log"
    [ -f "$LOG_DIR/opserver_node.log" ] && tail -20 "$LOG_DIR/opserver_node.log"
fi

echo ""
log "Dashboard URL: ${URL}/"
log "종료: bash $SCRIPT_DIR/stop_moca.sh"
echo ""

# 브라우저 자동 open — xdg-open 우선, fallback chain
open_browser() {
    local url=$1
    for cmd in xdg-open sensible-browser google-chrome chromium firefox; do
        if command -v "$cmd" >/dev/null 2>&1; then
            ("$cmd" "$url" >/dev/null 2>&1 &)
            log "브라우저 자동 open ($cmd): $url"
            return 0
        fi
    done
    log "★ 브라우저 자동 open 실패 — xdg-open/chrome/firefox 모두 없음"
    log "  수동 진입: $url"
    return 1
}

if [ "$NO_BROWSER" = 0 ]; then
    open_browser "${URL}/"
fi
