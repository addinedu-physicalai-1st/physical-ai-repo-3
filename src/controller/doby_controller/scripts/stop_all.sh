#!/bin/bash
# ============================================================
# stop_all.sh — moca 전체 stack 일괄 깨끗 종료 (PC + RPi)
#
# 사용:
#   bash <repo>/scripts/stop_all.sh            기본 (PC + RPi)
#   bash <repo>/scripts/stop_all.sh --hard     RPi daemon + SHM cache 까지 정리 (D 옵션)
#   bash <repo>/scripts/stop_all.sh --purge-shm  /dev/shm/fastdds_* 양쪽 정리만
#   bash <repo>/scripts/stop_all.sh --keep-rpi RPi bringup 유지
#   bash <repo>/scripts/stop_all.sh --keep-sim sim/gazebo 유지
#   bash <repo>/scripts/stop_all.sh --quiet    출력 최소
#   bash <repo>/scripts/stop_all.sh --dry-run  매칭만 표시
#
# 종료 대상:
#   - PC moca/dev_common/teleop_ui (stop_moca.sh --with-ui)
#   - PC robot_cam (있다면)
#   - RPi vic_pinky_bringup (stop_vic_bringup.sh)
#   - PC sim/gazebo 잔재 (--keep-sim 아닐 때)
#   - RPi ros2 daemon 재기동 (--hard 시) + DDS lease wait
#   - PC + RPi /dev/shm/fastdds_* 양쪽 정리 (--purge-shm 또는 --hard 시)
#   - PC ros2 daemon 재기동 (stale cache cleanup)
#
# --hard 추천 사유 (2026-05-18 doby 추천 D):
#   * PC 만 daemon restart → RPi daemon 의 DDS Participant entity 가 LAN sync 로
#     PC daemon 에 재 전파 → 좀비 node/publisher 잔재 (`/mode/state Publisher count: 4` 등).
#   * 영구 해결 = 양쪽 daemon + SHM 정리 + DDS lease wait.
#
# 환경 (override):
#   ROBOT_IP   기본 192.168.0.138
#   ROBOT_USER 기본 vic
#   ROBOT_PASS 기본 1
#
# 종료 후 검증:
#   - PC ros2 node list (moca/dobi_npc 잔재)
#   - RPi pgrep (bringup/sllidar/twist_mux 잔재)
#   - port 8765 (teleop_ui) free 여부
#
# 관련:
#   stop_moca.sh / stop_vic_bringup.sh / stop_robot_cam.sh / stop_sim.sh
# ============================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

KEEP_RPI=0
KEEP_SIM=0
DRY_RUN=0
QUIET=0
HARD=0
PURGE_SHM=0
for arg in "$@"; do
    case "$arg" in
        --keep-rpi)  KEEP_RPI=1 ;;
        --keep-sim)  KEEP_SIM=1 ;;
        --dry-run)   DRY_RUN=1 ;;
        --quiet)     QUIET=1 ;;
        --hard)      HARD=1; PURGE_SHM=1 ;;
        --purge-shm) PURGE_SHM=1 ;;
        -h|--help)
            sed -n '2,/^# =====*$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
    esac
done

log() { [ "$QUIET" = 1 ] || echo "$@"; }

log "======================================================"
log " moca 전체 stack 일괄 종료 (stop_all)"
log "======================================================"

DRY_OPT=""
[ "$DRY_RUN" = 1 ] && DRY_OPT="--dry-run"
QUIET_OPT=""
[ "$QUIET" = 1 ] && QUIET_OPT="--quiet"

# ── 1) PC moca/dev_common/teleop_ui ─────────────────────────────────────
log ""
log "[1/5] PC moca + teleop_ui 종료..."
bash "$SCRIPT_DIR/stop_moca.sh" --with-ui $DRY_OPT $QUIET_OPT

# ── 2) PC robot_cam (있으면) ─────────────────────────────────────────────
if [ -x "$SCRIPT_DIR/stop_robot_cam.sh" ]; then
    log ""
    log "[2/5] PC robot_cam 종료..."
    [ "$DRY_RUN" = 1 ] && log "(dry-run skip)" \
        || bash "$SCRIPT_DIR/stop_robot_cam.sh" 2>/dev/null || true
fi

# ── 3) RPi vic_pinky_bringup ─────────────────────────────────────────────
log ""
if [ "$KEEP_RPI" = 1 ]; then
    log "[3/5] RPi bringup 종료 SKIP (--keep-rpi)"
elif [ "$DRY_RUN" = 1 ]; then
    log "[3/5] RPi bringup 종료 (dry-run skip)"
else
    log "[3/5] RPi bringup 종료..."
    bash "$SCRIPT_DIR/stop_vic_bringup.sh"
fi

# ── 4) PC sim/gazebo 잔재 ────────────────────────────────────────────────
if [ "$KEEP_SIM" = 1 ]; then
    log ""
    log "[4/5] sim/gazebo 종료 SKIP (--keep-sim)"
elif [ -x "$SCRIPT_DIR/stop_sim.sh" ]; then
    log ""
    log "[4/5] PC sim/gazebo 잔재 종료..."
    [ "$DRY_RUN" = 1 ] && log "(dry-run skip)" \
        || bash "$SCRIPT_DIR/stop_sim.sh" 2>/dev/null || true
fi

# ── 5) DDS cache deep cleanup (--hard 또는 --purge-shm) ────────────────
ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=3"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"
RPI_REACHABLE=0
if [ "$DRY_RUN" = 0 ] && command -v sshpass >/dev/null && ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1; then
    RPI_REACHABLE=1
fi

if [ "$HARD" = 1 ] && [ "$DRY_RUN" = 0 ]; then
    log ""
    log "[5a] --hard — RPi ros2 daemon stop+start (DDS Participant entity 무효화)..."
    if [ "$RPI_REACHABLE" = 1 ]; then
        # batch — single ssh 로 daemon stop + daemon stop process kill + restart
        $RSSH "
          source /opt/ros/jazzy/setup.bash
          ros2 daemon stop  >/dev/null 2>&1 || true
          pkill -9 -f 'ros2-daemon\|ros2cli.daemon' 2>/dev/null || true
          sleep 1
          ros2 daemon start >/dev/null 2>&1 || true
        " 2>/dev/null && log "  ✓ RPi daemon restart 완료" \
                     || log "  ★ RPi daemon restart 실패 (ssh 또는 timeout)"
    else
        log "  RPi unreachable — skip"
    fi
fi

if [ "$PURGE_SHM" = 1 ] && [ "$DRY_RUN" = 0 ]; then
    log ""
    log "[5b] /dev/shm/fastdds_* 정리 (PC + RPi)..."
    pc_n=$(ls /dev/shm/fastdds_* 2>/dev/null | wc -l)
    if [ "$pc_n" -gt 0 ]; then
        rm -f /dev/shm/fastdds_* 2>/dev/null
        log "  PC: $pc_n 개 정리 ✓"
    else
        log "  PC: 없음 ✓"
    fi
    if [ "$RPI_REACHABLE" = 1 ]; then
        rpi_n=$($RSSH "ls /dev/shm/fastdds_* 2>/dev/null | wc -l" 2>/dev/null || echo 0)
        if [ "$rpi_n" -gt 0 ] 2>/dev/null; then
            $RSSH "rm -f /dev/shm/fastdds_* 2>/dev/null" 2>/dev/null
            log "  RPi: $rpi_n 개 정리 ✓"
        else
            log "  RPi: 없음 ✓"
        fi
    fi
fi

# DDS lease timeout wait (--hard 시 5s, 기본 1s)
if [ "$DRY_RUN" = 0 ] && command -v ros2 >/dev/null 2>&1; then
    log ""
    log "[5/5] PC ros2 daemon 재기동 (cache cleanup)..."
    ros2 daemon stop  >/dev/null 2>&1 || true
    pkill -9 -f 'ros2-daemon\|ros2cli.daemon' 2>/dev/null || true
    if [ "$HARD" = 1 ]; then
        log "  --hard: DDS lease timeout 대기 (5s)..."
        sleep 5
    else
        sleep 1
    fi
    ros2 daemon start >/dev/null 2>&1 || true
    sleep 1
fi

# ── 검증 ────────────────────────────────────────────────────────────────
if [ "$DRY_RUN" = 1 ]; then
    log ""
    log "======================================================"
    log " dry-run 완료 — 실제 종료는 옵션 빼고 재실행"
    log "======================================================"
    exit 0
fi

log ""
log "======================================================"
log " 검증"
log "======================================================"

# PC port (teleop_ui 8765)
for port in 8765; do
    if ss -tlnp 2>/dev/null | grep -q ":$port "; then
        log " ★ port $port  여전 listen 중 (외부 process — 수동 확인 필요)"
        [ "$QUIET" = 1 ] || ss -tlnp 2>/dev/null | grep ":$port " | sed 's/^/    /'
    else
        log " port $port  free ✓"
    fi
done

# PC ros2 node list — moca/dobi_npc 잔재
moca_nodes=$(timeout 3 ros2 node list 2>/dev/null \
    | grep -iE 'moca|mode_manager|task_orchestrator|patrol|guiding|serving|dobi_npc|persona|dialog_router|face_avatar|geva|rapport_tracker|tts' \
    || true)
if [ -z "$moca_nodes" ]; then
    log " PC ros2 node:  moca/dobi_npc 잔재 없음 ✓"
else
    log " ★ PC ros2 node:  잔재 발견 (DDS 캐시일 수도)"
    [ "$QUIET" = 1 ] || echo "$moca_nodes" | sort -u | sed 's/^/    /'
fi

# RPi 잔재 검증 (--keep-rpi 가 아니고 ssh 가능 시)
if [ "$KEEP_RPI" = 0 ]; then
    if [ "$RPI_REACHABLE" = 1 ]; then
        rpi_procs=$($RSSH "pgrep -af 'ros2 launch vicpinky\|sllidar\|twist_mux\|velocity_smoother\|collision_monitor\|collision_detector\|lifecycle_manager_safety\|robot_state_publisher\|vic_pinky_bringup' 2>/dev/null" || true)
        if [ -z "$rpi_procs" ]; then
            log " RPi process: bringup/lidar/twist_mux/smoother 잔재 없음 ✓"
        else
            log " ★ RPi process: 잔재 발견"
            [ "$QUIET" = 1 ] || echo "$rpi_procs" | sed 's/^/    /'
        fi
        # SHM 잔재 검증 (--hard 후 확인용)
        rpi_shm=$($RSSH "ls /dev/shm/fastdds_* 2>/dev/null | wc -l" 2>/dev/null || echo 0)
        if [ "$rpi_shm" -gt 0 ] 2>/dev/null; then
            log " ★ RPi /dev/shm/fastdds_*: $rpi_shm 개 잔존 (--purge-shm 권장)"
        else
            log " RPi /dev/shm/fastdds_*: 없음 ✓"
        fi
    else
        log " RPi 검증 SKIP (sshpass 없음 또는 RPi unreachable)"
    fi
fi

# PC SHM 검증
pc_shm=$(ls /dev/shm/fastdds_* 2>/dev/null | wc -l)
if [ "$pc_shm" -gt 0 ]; then
    log " ★ PC /dev/shm/fastdds_*: $pc_shm 개 잔존 (--purge-shm 권장)"
else
    log " PC /dev/shm/fastdds_*: 없음 ✓"
fi

# 카메라
log ""
log " 카메라 점유:"
for dev in /dev/video0 /dev/video2; do
    if [ -e "$dev" ]; then
        holders=$(fuser "$dev" 2>/dev/null | tr -d ' ')
        [ -z "$holders" ] && log "  $dev  free ✓" \
            || log "  $dev  ★ 점유 중: $holders"
    fi
done

log ""
log "======================================================"
log " stop_all 완료"
log "======================================================"
