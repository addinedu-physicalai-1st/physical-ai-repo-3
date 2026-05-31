#!/usr/bin/env bash
# run_nav2_sim.sh — Nav2 시뮬 풀 스택 순차 기동 + 단계별 health check.
#
# 순서: (1) Gazebo → (2) safety chain → (3) Nav2 bringup → (4) AMCL self-init → (5) RViz
# 격리: ROS_DOMAIN_ID=99 + ROS_LOCALHOST_ONLY=1 (시뮬 전용, RPi/팀 분리)
#
# 사용법:
#   scripts/run_nav2_sim.sh             # 전체 기동 (RViz 포함)
#   scripts/run_nav2_sim.sh --no-rviz   # RViz 제외
#   scripts/run_nav2_sim.sh --map=<yaml> # Nav2 map override
#   scripts/run_nav2_sim.sh --stop      # 전체 종료 (gz sim + Nav2 + RViz)
#
# 로그: /tmp/moca_nav2_sim_<ts>/{gazebo,nav2,rviz,initpose}.log
# 본 스크립트 자체 stdout = 단계별 health check 요약.

# set -u 금지: ROS setup.bash 내부 변수 (AMENT_TRACE_SETUP_FILES 등) 미정의 시 충돌

# ─────────────────────────────────────────────────────────────
# 환경
# ─────────────────────────────────────────────────────────────
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
TS="$(date +%Y%m%d_%H%M%S)"
LOGDIR="/tmp/moca_nav2_sim_${TS}"
GAZEBO_LOG="${LOGDIR}/gazebo.log"
NAV2_LOG="${LOGDIR}/nav2.log"
INITPOSE_LOG="${LOGDIR}/initpose.log"
RVIZ_LOG="${LOGDIR}/rviz.log"
SAFETY_LOG="${LOGDIR}/safety.log"

export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

# spawn pose — config/cafe_layout.yaml 의 pinky_spawn 동적 추출 (picker SoT).
# 파일 없으면 fallback (launch_mapv5_moca.launch.xml 와 동기화된 값).
CAFE_YAML="$REPO/config/cafe_layout.yaml"
if [ -f "$CAFE_YAML" ]; then
  SPAWN_X=$(python3 -c "import yaml; d=yaml.safe_load(open('$CAFE_YAML')); print(d['furniture']['pinky_spawn']['x'])" 2>/dev/null)
  SPAWN_Y=$(python3 -c "import yaml; d=yaml.safe_load(open('$CAFE_YAML')); print(d['furniture']['pinky_spawn']['y'])" 2>/dev/null)
  SPAWN_YAW=$(python3 -c "import yaml; d=yaml.safe_load(open('$CAFE_YAML')); print(d['furniture']['pinky_spawn']['yaw'])" 2>/dev/null)
fi
# 2026-05-17 (저녁) — dock vs staging 분리. sim fallback = staging.
SPAWN_X="${SPAWN_X:--36.98}"
SPAWN_Y="${SPAWN_Y:-2.0}"
SPAWN_YAW="${SPAWN_YAW:--1.571}"

# 색상 (TTY 일 때만)
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

# ─────────────────────────────────────────────────────────────
# 정리 (모든 단계 공통)
# ─────────────────────────────────────────────────────────────
SIM_PROCESS_PATTERN="ros2 launch moca_navigation|ros2 launch moca_gazebo|nav2_view.launch.xml|rviz2.*nav2|component_container_isolated.*nav2_container|parameter_bridge|image_bridge|scan_to_scan_filter_chain|laser_filter|robot_state_publisher|ros_gz_sim.*create"

list_sim_processes() {
  pgrep -af "$SIM_PROCESS_PATTERN" 2>/dev/null \
    | grep -v 'run_nav2_sim.sh' \
    | grep -v 'pgrep -af' \
    | grep -v ' grep ' \
    | grep -v 'claude'
}

list_gz_processes() {
  pgrep -af "gz sim" 2>/dev/null \
    | grep -v 'run_nav2_sim.sh' \
    | grep -v 'pgrep -af' \
    | grep -v ' grep ' \
    | grep -v 'claude'
}

stop_all() {
  list_sim_processes | awk '{print $1}' | xargs -r kill -TERM 2>/dev/null
  sleep 2

  list_sim_processes | awk '{print $1}' | xargs -r kill -KILL 2>/dev/null
  sleep 1

  # gz sim server/gui 잔존 강제. Gazebo 가 clock/tf 를 계속 내면 Nav2 TF buffer 가 time jump 로 초기화된다.
  list_gz_processes | awk '{print $1}' | xargs -r kill -KILL 2>/dev/null
  # ros2 daemon 정리는 안 함 (다른 사용자 토픽 영향)
  sleep 1
}

USE_RVIZ=1
NAV2_MAP=""
for arg in "$@"; do
  case "$arg" in
    --stop|stop)
      step "Nav2 시뮬 풀 스택 종료"
      stop_all
      remaining="$(list_sim_processes; list_gz_processes)"
      if [ -n "$remaining" ]; then
        warn "종료 후에도 잔존 프로세스 감지"
        echo "$remaining"
        exit 1
      fi
      ok "모두 종료됨"
      exit 0
      ;;
    --no-rviz)
      USE_RVIZ=0
      ;;
    --map=*)
      NAV2_MAP="${arg#*=}"
      ;;
    -h|--help)
      sed -n '2,/^# 본 스크립트/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      bad "알 수 없는 옵션: $arg"
      exit 1
      ;;
  esac
done

# ─────────────────────────────────────────────────────────────
# 사전 검사
# ─────────────────────────────────────────────────────────────
step "사전 검사"
mkdir -p "$LOGDIR"
dim "로그 디렉터리: $LOGDIR"

if [ ! -f /opt/ros/jazzy/setup.bash ]; then
  bad "ROS Jazzy 미설치 (/opt/ros/jazzy/setup.bash 없음)"
  exit 1
fi
ok "ROS Jazzy 발견"

if [ ! -f "$REPO/install/setup.bash" ]; then
  bad "워크스페이스 미빌드 ($REPO/install/setup.bash 없음). 'moca_build' 먼저."
  exit 1
fi
ok "워크스페이스 install/ 존재"

# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source "$REPO/install/setup.bash"
ok "ROS 환경 source 완료 (DOMAIN=$ROS_DOMAIN_ID, LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY)"

if [ -n "$NAV2_MAP" ]; then
  if [ ! -f "$NAV2_MAP" ]; then
    bad "Nav2 map override 미발견: $NAV2_MAP"
    exit 1
  fi
  ok "Nav2 map override: $NAV2_MAP"
else
  ok "Nav2 map override 없음 — moca_navigation launch 기본값 사용"
fi

# 기존 프로세스 정리
step "기존 잔존 프로세스 정리"
stop_all
remaining="$(list_sim_processes; list_gz_processes)"
if [ -n "$remaining" ]; then
  bad "이전 시뮬 인스턴스 잔존 — /clock, /tf 중복 방지를 위해 중단"
  echo "$remaining"
  exit 1
fi
ok "이전 인스턴스 종료 (있었다면)"

# ─────────────────────────────────────────────────────────────
# 1. Gazebo 기동
# ─────────────────────────────────────────────────────────────
step "[1/4] Gazebo 기동"
dim "world: mapv5_moca.world, spawn: ($SPAWN_X, $SPAWN_Y, yaw=$SPAWN_YAW)"
nohup ros2 launch moca_gazebo launch_mapv5_moca.launch.xml \
  > "$GAZEBO_LOG" 2>&1 &
GAZEBO_PID=$!
dim "launcher PID = $GAZEBO_PID, log = $GAZEBO_LOG"

# gz sim server 준비 대기 (최대 60초)
GZ_OK=0
for i in $(seq 1 30); do
  if pgrep -f "^gz sim -r -s" > /dev/null 2>&1; then
    GZ_OK=1; break
  fi
  sleep 2
done
[ $GZ_OK -eq 1 ] && ok "gz sim server 프로세스 기동" || { bad "gz sim 기동 실패 (로그 확인: $GAZEBO_LOG)"; exit 1; }

# /clock + /scan 대기 (Gazebo 가 토픽 발행할 때까지)
dim "토픽 대기: /clock, /scan, /odom (최대 30초)"
TOPICS_OK=0
for i in $(seq 1 15); do
  TOPICS=$(ros2 topic list 2>/dev/null)
  if grep -q "^/clock$" <<<"$TOPICS" && grep -q "^/scan$" <<<"$TOPICS" && grep -q "^/odom$" <<<"$TOPICS"; then
    TOPICS_OK=1; break
  fi
  sleep 2
done
if [ $TOPICS_OK -eq 1 ]; then
  ok "Gazebo 토픽 발행 확인 (/clock /scan /odom)"
else
  warn "Gazebo 토픽 일부 미발행 — 계속 진행하나 Nav2 실패 가능"
  dim "현재 토픽: $(ros2 topic list 2>/dev/null | tr '\n' ' ')"
fi

# ─────────────────────────────────────────────────────────────
# 2. Safety chain (velocity_smoother + collision_monitor)
# ─────────────────────────────────────────────────────────────
step "[2/5] Safety chain"
nohup ros2 launch moca_navigation safety_sim.launch.xml \
  > "$SAFETY_LOG" 2>&1 &
SAFETY_PID=$!
dim "launcher PID = $SAFETY_PID, log = $SAFETY_LOG"

SAFETY_OK=0
for i in $(seq 1 20); do
  NODES=$(ros2 node list 2>/dev/null)
  if grep -q "^/velocity_smoother$" <<<"$NODES" && grep -q "^/collision_monitor$" <<<"$NODES"; then
    SAFETY_OK=1; break
  fi
  sleep 1
done
[ $SAFETY_OK -eq 1 ] && ok "Safety nodes 기동 (/velocity_smoother /collision_monitor)" \
  || warn "Safety nodes 일부 미감지 — cmd_vel 안전 체인 로그 확인: $SAFETY_LOG"

# ─────────────────────────────────────────────────────────────
# 3. Nav2 bringup
# ─────────────────────────────────────────────────────────────
step "[3/5] Nav2 bringup"
# Sim runs use separate processes instead of a component container. The composed
# container can intermittently stall on /nav2_container/_container/load_node and
# never reach AMCL/lifecycle activation.
NAV2_ARGS=(use_sim_time:=True use_composition:=False)
if [ -n "$NAV2_MAP" ]; then
  NAV2_ARGS=(map:="$NAV2_MAP" "${NAV2_ARGS[@]}")
  dim "map override: $NAV2_MAP, use_sim_time: True"
else
  dim "map: moca_navigation launch default, use_sim_time: True"
fi
nohup ros2 launch moca_navigation bringup_launch.xml \
  "${NAV2_ARGS[@]}" \
  > "$NAV2_LOG" 2>&1 &
NAV2_PID=$!
dim "launcher PID = $NAV2_PID, log = $NAV2_LOG"

# Localization (map_server + amcl) active 대기 (최대 60초)
# 주의: `ros2 lifecycle get` 은 composable 노드 가시성 이슈로 빈 응답 가능 →
# nav2.log 의 lifecycle_manager 문자열을 신호로 사용 (더 신뢰).
dim "localization active 대기 (최대 60초) — 'lifecycle_manager_localization: Managed nodes are active'"
LOC_OK=0
for i in $(seq 1 30); do
  if grep -q "lifecycle_manager_localization.*Managed nodes are active" "$NAV2_LOG" 2>/dev/null; then
    LOC_OK=1; break
  fi
  sleep 2
done
[ $LOC_OK -eq 1 ] && ok "Localization active (map_server + amcl)" \
  || { warn "Localization active 미감지 — 진행하나 AMCL initial pose 실패 가능"; }

# ─────────────────────────────────────────────────────────────
# 4. AMCL self-init 대기 (yaml set_initial_pose=true → AMCL 가 yaml 의
#    initial_pose 좌표로 자기 init. 외부 /initialpose pub 불필요).
# ─────────────────────────────────────────────────────────────
# 2026-05-17 — 외부 /initialpose pub 제거. yaml self-init 만 사용.
# 이유: 외부 reset 시 "Failed to transform initial pose in time" + covariance
# reset 으로 wrong-basin jump 트리거 의심. AMCL set_initial_pose=true 가
# nav2_params.yaml line 52 에 명시되어 있어 외부 pub 불필요.
# yaml → quaternion (z, w) 는 warmup 단계에서 재사용.
step "[4/5] AMCL self-init 대기 (yaml set_initial_pose=true)"
dim "pose: yaml 의 amcl.initial_pose (set_initial_pose=true)"
QZ=$(python3 -c "import math; print(math.sin(${SPAWN_YAW}/2))")
QW=$(python3 -c "import math; print(math.cos(${SPAWN_YAW}/2))")
> "$INITPOSE_LOG"
AMCL_OK=0
for i in $(seq 1 15); do
  if grep -q "\[amcl\].*Setting pose" "$NAV2_LOG" 2>/dev/null; then
    AMCL_OK=1
    dim "AMCL initial pose 적용 로그 확인 (${i} s 대기 후)"
    break
  fi
  sleep 1
done
[ $AMCL_OK -eq 1 ] && ok "AMCL self-init 확인 (yaml initial_pose 적용)" || warn "AMCL self-init 미확인 — nav2.log 확인 필요"

# Navigation (controller/planner/bt/...) active 대기 (initial pose 후 TF 살아나서 활성)
dim "navigation active 대기 (최대 60초) — 'lifecycle_manager_navigation: Managed nodes are active'"
NAV_OK=0
for i in $(seq 1 30); do
  if grep -q "lifecycle_manager_navigation.*Managed nodes are active" "$NAV2_LOG" 2>/dev/null; then
    NAV_OK=1; break
  fi
  sleep 2
done
[ $NAV_OK -eq 1 ] && ok "Navigation active (planner + controller + bt + ...)" \
  || warn "Navigation active 미감지 — global_costmap 의 map TF 미확립 가능. nav2.log 확인."

# ─────────────────────────────────────────────────────────────
# 3.5 Nav2 warmup — 현 위치로 NavigateToPose 1회 (costmap + bt + AMCL 완전 활성).
# 첫 실 nav 시 dispatcher 가 cold AMCL race 로 stuck 되는 사고 회피.
# ─────────────────────────────────────────────────────────────
WARMUP_OK=0
if [ $NAV_OK -eq 1 ]; then
  dim "Nav2 warmup — 현 위치로 단발 NavigateToPose (cold start 회피)"
  WARMUP_LOG="${LOGDIR}/warmup.log"
  timeout 20 ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
    "{pose: {header: {frame_id: 'map'},
             pose: {position: {x: ${SPAWN_X}, y: ${SPAWN_Y}, z: 0.0},
                    orientation: {x: 0.0, y: 0.0, z: ${QZ}, w: ${QW}}}}}" \
    >"$WARMUP_LOG" 2>&1
  if grep -q "SUCCEEDED" "$WARMUP_LOG"; then
    WARMUP_OK=1
    ok "Nav2 warmup 성공 (SUCCEEDED)"
  else
    warn "Nav2 warmup 미완료 — 첫 실 nav 시 stuck 가능 (log: $WARMUP_LOG)"
  fi
fi

# ─────────────────────────────────────────────────────────────
# 5. RViz
# ─────────────────────────────────────────────────────────────
if [ $USE_RVIZ -eq 1 ]; then
  step "[5/5] RViz (nav2_view)"
  nohup ros2 launch moca_navigation nav2_view.launch.xml \
    use_sim_time:=True \
    > "$RVIZ_LOG" 2>&1 &
  RVIZ_PID=$!
  dim "launcher PID = $RVIZ_PID, log = $RVIZ_LOG"
  sleep 4
  if pgrep -f "rviz2" > /dev/null 2>&1; then
    ok "RViz 기동"
  else
    warn "RViz 미감지 (로그 확인: $RVIZ_LOG)"
  fi
else
  step "[5/5] RViz — --no-rviz 옵션으로 건너뜀"
fi

# ─────────────────────────────────────────────────────────────
# 최종 요약
# ─────────────────────────────────────────────────────────────
step "최종 health check"
ros2 node list 2>/dev/null | sort > "$LOGDIR/nodes.txt"
ros2 topic list 2>/dev/null | sort > "$LOGDIR/topics.txt"
NODE_COUNT=$(wc -l < "$LOGDIR/nodes.txt")
TOPIC_COUNT=$(wc -l < "$LOGDIR/topics.txt")
dim "active node : $NODE_COUNT (목록: $LOGDIR/nodes.txt)"
dim "active topic: $TOPIC_COUNT (목록: $LOGDIR/topics.txt)"

if grep -q "^/collision_monitor$" "$LOGDIR/nodes.txt" && grep -q "^/collision_monitor_state$" "$LOGDIR/topics.txt"; then
  ok "collision_monitor active topic 확인 (/collision_monitor_state)"
else
  warn "collision_monitor 상태 토픽 미확인 — 안전 체인 로그 확인: $SAFETY_LOG"
fi

# /tf 발행 확인 (map → odom → base_footprint 체인).
# Nav2 params 의 AMCL/global_costmap/bt_navigator 기준 프레임은 base_footprint 이다.
TF_TARGET_FRAME="base_footprint"
TF_OK=$(timeout 5 ros2 run tf2_ros tf2_echo map "$TF_TARGET_FRAME" 2>&1 | grep -c "Translation")
if [ "$TF_OK" -ge 1 ]; then
  ok "/tf 체인 map→${TF_TARGET_FRAME} OK"
elif [ "$WARMUP_OK" -eq 1 ]; then
  ok "/tf 체인 map→${TF_TARGET_FRAME} OK (warmup 성공으로 확인)"
else
  warn "/tf map→${TF_TARGET_FRAME} 미확립 (Gazebo 시뮬 클럭/AMCL 대기 중일 수 있음)"
fi

echo
ok "Nav2 시뮬 스택 기동 완료"
dim "종료: scripts/run_nav2_sim.sh --stop"
dim "로그 위치: $LOGDIR"
echo
echo "다음 액션 예시:"
dim "  # NavigateToPose 단발 테스트 (T01 으로 이동)"
dim "  ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \\"
dim "    \"{pose: {header: {frame_id: map}, pose: {position: {x: -36.337, y: 0.526, z: 0}, orientation: {w: 1}}}}\""
dim "  # serving_dispatcher 별도 실행"
dim "  ros2 launch dobi_npc_bringup mode_serving.launch.py"
