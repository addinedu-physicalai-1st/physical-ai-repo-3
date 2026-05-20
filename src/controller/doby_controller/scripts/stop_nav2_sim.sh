#!/usr/bin/env bash
# stop_nav2_sim.sh — run_nav2_sim.sh 가 띄운 모든 프로세스 종료 + 정리 검증.
#
# 단계: (1) launcher SIGTERM → (2) child SIGTERM → (3) 잔존 SIGKILL → (4) 검증
# 검증 항목:
#   - pgrep: gz sim / ros2 launch moca_* / rviz2 / nav2_container 잔존 0
#   - ros2 topic list: /scan /clock /amcl_pose /map 미공급 (다른 워크스페이스 발행 제외 위해 DOMAIN=99 격리 유지)
#   - ros2 node list: /amcl /map_server /bt_navigator 미존재
#
# 격리: ROS_DOMAIN_ID=99 + ROS_LOCALHOST_ONLY=1 (run_nav2_sim.sh 와 동일)
#
# 사용법:
#   scripts/stop_nav2_sim.sh           # 정상 종료 + 검증
#   scripts/stop_nav2_sim.sh --force   # 처음부터 SIGKILL (긴급)

# set -u 금지: ROS setup.bash 내부 변수 미정의 시 충돌

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

# 색상
if [ -t 1 ]; then
  C_OK=$'\033[1;32m'; C_BAD=$'\033[1;31m'; C_WARN=$'\033[1;33m'
  C_DIM=$'\033[0;90m'; C_RST=$'\033[0m'
else
  C_OK=""; C_BAD=""; C_WARN=""; C_DIM=""; C_RST=""
fi
ok()   { printf "%s[OK]%s   %s\n" "$C_OK" "$C_RST" "$*"; }
bad()  { printf "%s[FAIL]%s %s\n" "$C_BAD" "$C_RST" "$*"; }
warn() { printf "%s[WARN]%s %s\n" "$C_WARN" "$C_RST" "$*"; }
step() { printf "\n%s== %s ==%s\n" "$C_OK" "$*" "$C_RST"; }
dim()  { printf "%s%s%s\n" "$C_DIM" "$*" "$C_RST"; }

# 대상 패턴 (claude 자체 셸 제외)
# 주의: ros2 launch dobi_npc_bringup 도 포함 (mode_serving 등 향후 dispatcher)
TOP_PATTERNS=(
  "ros2 launch moca_navigation"
  "ros2 launch moca_gazebo"
  "ros2 launch dobi_npc_bringup"
)
CHILD_PATTERNS=(
  "^gz sim "
  "ruby .*gz_tools_vendor.*gz sim"
  "rviz2"
  "component_container.*nav2"
  "nav2_container"
  "robot_state_publisher"
  "spawner.*ros_gz"
  "parameter_bridge"
  "image_bridge"
)
# Nav2 composable 노드가 standalone 실행되는 경우 (드물지만 대비)
STANDALONE_PATTERNS=(
  "nav2_amcl"
  "nav2_map_server"
  "nav2_planner_server"
  "nav2_controller_server"
  "nav2_bt_navigator"
  "nav2_behavior_server"
  "nav2_smoother_server"
  "nav2_velocity_smoother"
  "nav2_lifecycle_manager"
  "nav2_waypoint_follower"
)

list_targets() {
  # 모든 패턴 매칭 PID 출력 (중복 제거, claude/grep/pgrep/본 스크립트 자체 제외)
  local pat
  local pids=""
  for pat in "${TOP_PATTERNS[@]}" "${CHILD_PATTERNS[@]}" "${STANDALONE_PATTERNS[@]}"; do
    pids+="$(pgrep -af "$pat" 2>/dev/null \
              | grep -v claude \
              | grep -v stop_nav2_sim.sh \
              | grep -v run_nav2_sim.sh \
              | awk '{print $1}')\n"
  done
  printf "%b" "$pids" | sort -un | grep -v '^$'
}

kill_targets() {
  local sig="$1"; shift
  local pids
  pids="$(list_targets)"
  if [ -z "$pids" ]; then return 0; fi
  dim "[$sig] 대상 PID: $(tr '\n' ' ' <<<"$pids")"
  while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    # 본인/부모 회피
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "$PPID" ] && continue
    kill "-$sig" "$pid" 2>/dev/null || true
  done <<<"$pids"
}

# ─────────────────────────────────────────────────────────────
# 사전 — ROS source (검증 단계용)
# ─────────────────────────────────────────────────────────────
if [ -f /opt/ros/jazzy/setup.bash ]; then
  # shellcheck disable=SC1091
  source /opt/ros/jazzy/setup.bash
fi
if [ -f "$REPO/install/setup.bash" ]; then
  # shellcheck disable=SC1091
  source "$REPO/install/setup.bash"
fi

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

# ─────────────────────────────────────────────────────────────
# 0. 초기 현황
# ─────────────────────────────────────────────────────────────
step "초기 현황 확인 (DOMAIN=$ROS_DOMAIN_ID)"
INITIAL="$(list_targets)"
if [ -z "$INITIAL" ]; then
  ok "이미 깨끗 — 종료할 프로세스 없음"
  exit 0
fi
INIT_COUNT=$(printf "%s\n" "$INITIAL" | wc -l)
dim "감지된 대상 프로세스: ${INIT_COUNT} 개"
printf "%s\n" "$INITIAL" | while read -r p; do
  CMD=$(ps -p "$p" -o args= 2>/dev/null | cut -c1-80)
  printf "  %-7s %s\n" "$p" "$CMD"
done

# ─────────────────────────────────────────────────────────────
# 1. SIGTERM (top-level launcher 부터)
# ─────────────────────────────────────────────────────────────
if [ $FORCE -eq 0 ]; then
  step "[1/3] SIGTERM (정상 종료 시도, 5초 대기)"
  kill_targets TERM
  sleep 5
  REMAIN1="$(list_targets)"
  REMAIN1_COUNT=$([ -z "$REMAIN1" ] && echo 0 || printf "%s\n" "$REMAIN1" | wc -l)
  if [ "$REMAIN1_COUNT" -eq 0 ]; then
    ok "SIGTERM 만으로 모두 종료 (${INIT_COUNT} → 0)"
  else
    dim "잔존 ${REMAIN1_COUNT}개, SIGKILL 단계 진행"
  fi
else
  warn "--force 옵션: SIGTERM 건너뛰고 바로 SIGKILL"
fi

# ─────────────────────────────────────────────────────────────
# 2. SIGKILL (잔존 강제)
# ─────────────────────────────────────────────────────────────
step "[2/3] SIGKILL (잔존 강제 종료)"
kill_targets KILL
sleep 2

# ─────────────────────────────────────────────────────────────
# 3. 검증
# ─────────────────────────────────────────────────────────────
step "[3/3] 검증"
REMAIN="$(list_targets)"
if [ -z "$REMAIN" ]; then
  ok "프로세스 잔존 0"
else
  REMAIN_COUNT=$(printf "%s\n" "$REMAIN" | wc -l)
  bad "잔존 ${REMAIN_COUNT}개:"
  printf "%s\n" "$REMAIN" | while read -r p; do
    CMD=$(ps -p "$p" -o args= 2>/dev/null | cut -c1-80)
    printf "  %-7s %s\n" "$p" "$CMD"
  done
  warn "수동 확인 필요: ps -ef | grep -E 'gz sim|moca_(gazebo|navigation)|rviz2'"
fi

# 토픽/노드 발행 잔존 확인 (ros2 daemon 의 잔존 캐시는 자체 cleanup 이슈 — 가능한 정보만)
dim "ros2 daemon 캐시 reset (cleanup)"
ros2 daemon stop > /dev/null 2>&1 || true
sleep 1

# 새 daemon 으로 실측
dim "토픽/노드 실측 (DOMAIN=$ROS_DOMAIN_ID)"
TOPICS=$(timeout 3 ros2 topic list 2>/dev/null)
NODES=$(timeout 3 ros2 node list 2>/dev/null)
BAD_TOPICS=$(echo "$TOPICS" | grep -E "^/(clock|scan|amcl_pose|map|odom|tf|cmd_vel)$" || true)
BAD_NODES=$(echo "$NODES" | grep -E "/(amcl|map_server|bt_navigator|controller_server|planner_server|behavior_server|smoother_server|nav2_velocity_smoother|gazebo)" || true)

if [ -z "$BAD_TOPICS" ]; then
  ok "Nav2/Gazebo 토픽 미발견"
else
  warn "잔존 토픽: $(echo "$BAD_TOPICS" | tr '\n' ' ')"
fi
if [ -z "$BAD_NODES" ]; then
  ok "Nav2/Gazebo 노드 미발견"
else
  warn "잔존 노드: $(echo "$BAD_NODES" | tr '\n' ' ')"
fi

# 최종 종합
echo
if [ -z "$REMAIN" ] && [ -z "$BAD_TOPICS" ] && [ -z "$BAD_NODES" ]; then
  ok "Nav2 시뮬 스택 완전 종료 (프로세스/토픽/노드 모두 클린)"
  exit 0
else
  warn "일부 잔존 — 재실행 시 충돌 가능성. --force 또는 수동 정리 필요."
  exit 1
fi
