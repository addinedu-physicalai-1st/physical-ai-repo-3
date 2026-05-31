#!/bin/bash
# ============================================================
# stop_moca.sh — moca 노드/launch 깨끗 종료 + 좀비 정리
#
# 배경:
#   * 2026-05-06 좀비 사고:
#       ros2 launch 부모를 Ctrl+C 로 죽여도 자식 노드들이 orphan 으로 남고
#       좀비 geva_node 가 카메라 1 점유 → 새 시동 시 카메라 못 잡고 즉사.
#   * 2026-05-16 좀비 50+ 사고 (회고 §4.2):
#       ros2 run / ros2 launch / 통합 스모크 반복으로 mode_manager 9+,
#       patrol_scheduler 12, mode_patrol.launch 7+, guiding_controller 2,
#       person_detector 2, table_occupancy_detector 1 등 누적.
#       → mode_state publisher 11개 race → mode-badge 깜박 + 잘못된 자동
#         모드 전이 위험.
#
# 사용:
#   bash <repo>/scripts/stop_moca.sh                # moca/dobi_npc 노드 정리
#   bash <repo>/scripts/stop_moca.sh --with-ui      # teleop_server (운영 UI) 까지
#   bash <repo>/scripts/stop_moca.sh --no-daemon    # ros2 daemon 재기동 skip
#   bash <repo>/scripts/stop_moca.sh --dry-run      # 매칭만 표시, kill 안 함
#   bash <repo>/scripts/stop_moca.sh --quiet        # 출력 최소
#
# 절차:
#   1. 패턴 매칭 process 목록
#   2. (dry-run 아니면) SIGTERM → 2초 → 남은 것 SIGKILL → 1초
#   3. (--no-daemon 아니면) ros2 daemon stop/start
#   4. 검증 — moca 노드 잔재 + /mode/state publisher count
#   5. 카메라 점유 + audio sink mute 확인
#
# 종료 패턴:
#   moca/install/  ros2 launch  ros2 run dobi_npc
#   mode_manager  task_orchestrator  doby_debug_monitor
#   patrol_scheduler  guiding_controller
#   table_occupancy_detector  serving_dispatcher  person_detector  follow_controller
# ============================================================

set -u

WITH_UI=0
DAEMON_RESET=1
DRY_RUN=0
QUIET=0
for arg in "$@"; do
    case "$arg" in
        --with-ui)        WITH_UI=1 ;;
        --no-daemon)      DAEMON_RESET=0 ;;
        --dry-run)        DRY_RUN=1 ;;
        --quiet)          QUIET=1 ;;
        -h|--help)
            sed -n '2,/^# =====*$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
    esac
done

log() { [ "$QUIET" = 1 ] || echo "$@"; }

# 패턴 — 회고 §4.2 의 좀비 누적 패턴 망라.
# ros2 run / ros2 launch 부모 + entry point 직접 (python3 .../mode_manager 등).
PATTERNS=(
    'moca/install/'
    'ros2 launch'
    'ros2 run dobi_npc'
    'ros2 run debug_monitor'
    'mode_manager'
    'task_orchestrator'
    'doby_debug_monitor'
    'patrol_scheduler'
    'guiding_controller'
    'table_occupancy_detector'
    'table_markers'
    'serving_dispatcher'
    'person_detector'
    'follow_controller'
    'minigame_runner'
)
[ "$WITH_UI" = 1 ] && PATTERNS+=('web/teleop_server.py')

PATTERN_RE=$(IFS='|'; echo "${PATTERNS[*]}")

# 본 스크립트 자체 + grep / pgrep / awk / sed 자체 제외.
list_targets() {
    pgrep -af "$PATTERN_RE" 2>/dev/null \
        | grep -v 'stop_moca.sh' \
        | grep -v 'pgrep -af' \
        | grep -v ' grep ' \
        | grep -v 'list_targets'
}

initial=$(list_targets)

if [ -z "$initial" ]; then
    log "(moca 프로세스 없음 — 이미 정리됨)"
else
    if [ "$DRY_RUN" = 1 ]; then
        log "[stop_moca] DRY-RUN — 매칭 패턴:"
        echo "$initial" | awk '{printf "  pid=%-7s %s\n", $1, substr($0, index($0,$2))}'
        log "[stop_moca] (--dry-run) kill 생략. 실제 종료는 옵션 빼고 재실행."
        exit 0
    fi

    log "[stop_moca] 종료 대상 ($(echo "$initial" | wc -l) 개):"
    [ "$QUIET" = 1 ] || echo "$initial" \
        | awk '{printf "  pid=%-7s %s\n", $1, substr($0, index($0,$2))}'

    log "[stop_moca] SIGTERM..."
    echo "$initial" | awk '{print $1}' | xargs -r kill -TERM 2>/dev/null
    sleep 2

    remaining=$(list_targets)
    if [ -n "$remaining" ]; then
        log "[stop_moca] SIGTERM 후 $(echo "$remaining" | wc -l) 개 잔존 — SIGKILL..."
        echo "$remaining" | awk '{print $1}' | xargs -r kill -KILL 2>/dev/null
        sleep 1
    fi

    final=$(list_targets)
    if [ -n "$final" ]; then
        log "[stop_moca] ★ 경고 — SIGKILL 후에도 잔존:"
        [ "$QUIET" = 1 ] || echo "$final" \
            | awk '{printf "  pid=%-7s %s\n", $1, substr($0, index($0,$2))}'
    else
        log "[stop_moca] 모든 프로세스 정리 완료."
    fi
fi

# ─── ros2 daemon stale cache cleanup (회고 §4.2 권장) ────────────────────
if [ "$DAEMON_RESET" = 1 ] && command -v ros2 >/dev/null 2>&1; then
    log ""
    log "[stop_moca] ros2 daemon 재기동 (stale topic/node cache cleanup)..."
    ros2 daemon stop  >/dev/null 2>&1 || true
    sleep 1
    ros2 daemon start >/dev/null 2>&1 || true
    sleep 1
fi

# ─── 검증 — moca 노드 + /mode/state publisher count ───────────────────────
if command -v ros2 >/dev/null 2>&1; then
    log ""
    log "[stop_moca] 잔재 검증:"

    # moca 노드 잔재
    moca_nodes=$(timeout 3 ros2 node list 2>/dev/null \
        | grep -iE 'moca|mode_manager|task_orchestrator|patrol|guiding|serving_dispatcher' \
        || true)
    if [ -z "$moca_nodes" ]; then
        log "  ros2 node list: moca 관련 노드 없음 ✓"
    else
        log "  ★ ros2 node list: 잔재 발견"
        [ "$QUIET" = 1 ] || echo "$moca_nodes" | sed 's/^/    /'
    fi

    # mode_state publisher count (1 초과 시 race — 회고 §4.2 의 11개 사고)
    pub_count=$(timeout 3 ros2 topic info /mode/state 2>/dev/null \
        | awk '/Publisher count:/ {print $3; exit}' || true)
    if [ -n "$pub_count" ]; then
        if [ "$pub_count" -le 1 ] 2>/dev/null; then
            log "  /mode/state Publisher count: ${pub_count} ✓"
        else
            log "  ★ /mode/state Publisher count: ${pub_count} (정상=0|1, 초과=좀비 race)"
        fi
    fi
fi

# ─── 카메라 점유 해제 ─────────────────────────────────────────────────────
log ""
log "[stop_moca] 카메라 점유 상태:"
for dev in /dev/video0 /dev/video2; do
    if [ -e "$dev" ]; then
        holders=$(fuser "$dev" 2>/dev/null | tr -d ' ')
        if [ -z "$holders" ]; then
            log "  $dev   free ✓"
        else
            log "  $dev   ★ 점유 중: $holders (외부 프로세스)"
        fi
    else
        log "  $dev   (디바이스 없음)"
    fi
done

# ─── 사운드 sink mute 확인 ───────────────────────────────────────────────
if command -v wpctl >/dev/null 2>&1; then
    sink_line=$(wpctl status 2>/dev/null \
        | awk '/Sinks:/,/Sink endpoints:/' | grep -m1 '\*')
    if [ -n "$sink_line" ]; then
        log ""
        log "[stop_moca] default audio sink:"
        log "  $sink_line"
        if echo "$sink_line" | grep -q MUTED; then
            log "  ★ MUTED — 다음 시동 전에 음소거 해제 권장:"
            log "      wpctl set-mute @DEFAULT_AUDIO_SINK@ 0"
        fi
    fi
fi
