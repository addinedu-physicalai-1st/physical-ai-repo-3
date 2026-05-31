#!/bin/bash
# ============================================================
# run_dashboard.sh — ROS-only 운영 공통 노드 기동 (legacy wrapper)
#
# 사용:
#   bash <repo>/scripts/run_dashboard.sh             # 기본
#   bash <repo>/scripts/run_dashboard.sh --cleanup   # 시작 전 좀비 정리
#   bash <repo>/scripts/run_dashboard.sh --no-browser # 호환 옵션 (동작 없음)
#   bash <repo>/scripts/run_dashboard.sh --verbose   # stdout 콘솔 직접
#   bash <repo>/scripts/run_dashboard.sh --domain=22 # 실물 (§0-A 해제 시점만)
#   bash <repo>/scripts/run_dashboard.sh --domain=99 # 시뮬 (default, Gazebo + PC 단독)
#
# 기동:
#   1. CLAUDE.md §0-A 정합 — DOMAIN 기본 99 + LOCALHOST_ONLY=1 (시뮬)
#      --domain=22 시 실물 모드 (LOCALHOST_ONLY=0 + §0-A 정책 검증 필요)
#   2. ROS jazzy + install/setup.bash source
#   3. mode_manager + task_orchestrator + table_markers setsid 분리 spawn
#   4. ROS node/service 확인
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
DOMAIN=99
for arg in "$@"; do
    case "$arg" in
        --cleanup)    CLEANUP=1 ;;
        --no-browser) NO_BROWSER=1 ;;
        --verbose)    VERBOSE=1 ;;
        --port=*)     : ;;  # removed with HTTP server; accepted for legacy scripts
        --domain=*)   DOMAIN="${arg#*=}" ;;
        --test-mode)  : ;;  # removed with HTTP server
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
    setsid ros2 run mobility_controller table_markers &
else
    setsid ros2 run mobility_controller table_markers \
        >"$LOG_DIR/table_markers.log" 2>&1 &
fi
sleep 1

# task_orchestrator
log "task_orchestrator 시작..."
if [ "$VERBOSE" = 1 ]; then
    setsid ros2 run dobi_npc_bringup task_orchestrator &
else
    setsid ros2 run dobi_npc_bringup task_orchestrator \
        >"$LOG_DIR/task_orchestrator.log" 2>&1 &
fi

# Health check
log "3초 대기 후 ROS service check..."
sleep 3
if ros2 service list | grep -qx '/task/request_serving' && \
   ros2 service list | grep -qx '/mode/request'; then
    log "✓ ROS-only 운영 서비스 확인 OK"
else
    log "★ ROS service check 실패 — 로그 확인:"
    log "  $LOG_DIR/mode_manager.log"
    log "  $LOG_DIR/task_orchestrator.log"
    [ -f "$LOG_DIR/task_orchestrator.log" ] && tail -20 "$LOG_DIR/task_orchestrator.log"
fi

echo ""
log "ROS service: /mode/request, /task/request_serving, /task/request_guiding"
log "종료: bash $SCRIPT_DIR/stop_moca.sh"
echo ""
