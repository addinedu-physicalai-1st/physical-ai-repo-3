#!/bin/bash
# ============================================================
# stop_real.sh — run_real.sh 가 띄운 노트북 측 운영 UI 종료
#
# 본 스크립트는 노트북 (운영 UI) 측만 정리. RPi 노드는 §0-A 정책 따라
# 직접 정리 (RPi SSH 또는 운영자가 별도 절차).
#
# 사용:
#   bash <repo>/scripts/stop_real.sh
# ============================================================

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/stop_moca.sh" "$@"
