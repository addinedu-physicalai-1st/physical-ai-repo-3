#!/bin/bash
# ============================================================
# run_real.sh — 실물 로봇 환경 운영 UI 기동 (DOMAIN=22)
#
# 사용:
#   bash <repo>/scripts/run_real.sh [--force]    # §0-A 정책 prompt 후 기동
#
# 환경: ROS_DOMAIN_ID=22 + ROS_LOCALHOST_ONLY=0 (LAN broadcast, RPi/노트북 통신)
#
# ⚠ CLAUDE.md §0-A 정책:
#   동료가 실물 Vic Pinky 사용 중 신호 시 SSH/sshpass/scp/DOMAIN=22 모두 차단.
#   본 스크립트 실행 전 RPi 사용 OK 명시 확인 필수.
#   --force 옵션은 사용자 책임 (예: 사용자 본인이 단독 실 로봇 작업 중).
#
# RPi 노드 (zlac_driver / twist_mux / collision_monitor 등) 는 본 스크립트가
# 띄우지 않음. 별도 절차로 RPi 측에서 직접 기동 (run_teleop_ui.sh 또는
# run_vic_bringup.sh — §0-A 정책 통과 시점만).
#
# 종료: bash <repo>/scripts/stop_real.sh
# ============================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -h|--help)
            sed -n '2,/^# =====*$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "알 수 없는 옵션: $arg" >&2; exit 1 ;;
    esac
done

log() { echo "[run_real] $*"; }

# §0-A 정책 prompt
if [ "$FORCE" = 0 ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo " ⚠ CLAUDE.md §0-A 정책 확인"
    echo "════════════════════════════════════════════════════════════════"
    echo " 본 스크립트는 ROS_DOMAIN_ID=22 (실물 Vic Pinky LAN) 으로 기동합니다."
    echo " 동료가 실물 로봇을 사용 중이라면 토픽 충돌 / 안전 위험 발생."
    echo ""
    echo " 다음을 확인하셨습니까?"
    echo "   1. 실물 Vic Pinky (192.168.0.138) 가 본인 단독 사용 중인가?"
    echo "   2. 동료에게 RPi 사용 OK 신호를 받았는가?"
    echo "   3. 안전 영역 침입 대응 (collision_monitor) 준비됐는가?"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    read -p "위 3건 모두 확인. 계속 진행하시겠습니까? [y/N]: " ans
    case "$ans" in
        [yY]|[yY][eE][sS]) ;;
        *)  log "취소됨."
            exit 0
            ;;
    esac
fi

log "DOMAIN=22 실물 모드 운영 UI 기동..."
exec bash "$SCRIPT_DIR/run_dashboard.sh" --domain=22 "$@"
