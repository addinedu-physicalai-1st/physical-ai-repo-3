#!/bin/bash
# ============================================================
# moca_env.sh — moca 워크스페이스 빌드/활성화 단축 명령
#
# 사용법 (source 해야 현재 셸에 함수가 들어옴):
#   source ~/physical-ai-repo-3/src/controller/doby_controller/scripts/moca_env.sh
#
# 로드 후 사용 가능 명령:
#   moca_cd        — 워크스페이스 루트로 이동
#   moca_build     — 격리 셸에서 colcon 빌드 (.bashrc 의 robot_arm 영향 회피)
#   moca_activate  — install/setup.bash source
#   moca_clean     — build/install/log 삭제
#
# 환경변수:
#   MOCA_WS_ROOT   — 워크스페이스 절대경로 (스크립트 위치에서 자동 추정)
#
# CLAUDE.md §7 격리 셸 빌드 + §3 워크스페이스 구조 정합.
# ============================================================

# 스크립트 위치에서 워크스페이스 루트 추정 (SCRIPT_DIR/..)
if [ -n "${BASH_SOURCE[0]}" ]; then
    _moca_self="${BASH_SOURCE[0]}"
else
    _moca_self="$0"
fi
_moca_dir="$(cd "$(dirname "$_moca_self")" && pwd)"
export MOCA_WS_ROOT="$(cd "$_moca_dir/.." && pwd)"
unset _moca_self _moca_dir

moca_cd() {
    cd "$MOCA_WS_ROOT" || return 1
}

moca_build() {
    bash --noprofile --norc -c "cd \"$MOCA_WS_ROOT\" && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install"
}

moca_activate() {
    # shellcheck disable=SC1091
    source "$MOCA_WS_ROOT/install/setup.bash"
}

moca_clean() {
    rm -rf "$MOCA_WS_ROOT/build" "$MOCA_WS_ROOT/install" "$MOCA_WS_ROOT/log"
}

echo "[moca env loaded] MOCA_WS_ROOT=$MOCA_WS_ROOT"
echo "  명령: moca_cd | moca_build | moca_activate | moca_clean"
