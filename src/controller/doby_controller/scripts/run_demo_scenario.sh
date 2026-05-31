#!/bin/bash
# run_demo_scenario.sh — 5 모드 데모 시나리오 (ROS action/service 자동).
#
# 전제: run_sim.sh 가 떠 있음 (Gazebo + Nav2 + dashboard, DOMAIN=99).
#       mode=idle 상태에서 시작.
#
# 시퀀스:
#   [00:00] idle 인트로 8s
#   [00:08] patrol — 5 테이블 sweep + 자동 idle 복귀 (~90-120s)
#   [~02:00] serving — pickup T03 → Nav2 → 자동 idle (~45-60s)
#   [~03:00] guiding — T01 안내 → customer 없어 lock_on timeout aborted (~15s)
#   [~03:15] engaging — 모객 stack 진입 8s → 수동 idle
#   [~03:25] emergency_stop — ALARM 5s + 자동 복귀
#   [~03:35] 종료 idle 5s

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"

set +u
source /opt/ros/jazzy/setup.bash
source "$WS/install/setup.bash"
set -u

current_mode() {
  timeout 2 ros2 topic echo --once /mode/state --field current_mode 2>/dev/null | tail -1
}

set_mode() {
  local mode="$1" params="${2:-}" override="${3:-false}"
  ros2 service call /mode/request dobi_npc_msgs/srv/SetMode \
    "{requested_mode: '$mode', params: '$params', override_priority: $override}" >/dev/null
}

wait_mode() {
  local target="$1" timeout="${2:-60}"
  for i in $(seq 1 "$timeout"); do
    local m=$(current_mode)
    [ "$m" = "$target" ] && { echo "  → mode=$target (${i}s)"; return 0; }
    sleep 1
  done
  echo "  ⚠ timeout — current=$(current_mode)"
  return 1
}

stamp() { date +%H:%M:%S; }
T0=$(date +%s)
elapsed() { echo "[$(( $(date +%s) - T0 ))s]"; }

echo "==================================================="
echo "$(stamp) 데모 시나리오 시작 — moca 5 모드"
echo "==================================================="

# 1. 인트로 — idle 상태 안정 + 시청자 컨텍스트 파악
echo "$(elapsed) [1/6] idle 인트로 (8s)"
sleep 8

# 2. patrol — 5 테이블 sweep (가장 시각적)
echo "$(elapsed) [2/6] patrol 트리거 → 5 테이블 sweep"
set_mode patrol '{}' true
sleep 3
wait_mode idle 140 || true     # 자동 idle 복귀 (completion_watcher 1s dwell)
sleep 2

# 3. serving — pickup T03
echo "$(elapsed) [3/6] pickup T03 → serving 모드"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ros2 action send_goal /serving/execute dobi_npc_msgs/action/Serving \
  "{event_id: 'demo-$(date +%s)', drink_id: 'D-demo', order_id: '', target_table: 'T03', via_pickup: true, has_drink: true}" >/dev/null
sleep 3
wait_mode idle 90 || true
sleep 2

# 4. guiding — T01 안내 (customer 없어 lock_on 10s timeout aborted)
echo "$(elapsed) [4/6] guide T01 → guiding 모드 (lock_on timeout 예상)"
ros2 service call /task/request_guiding dobi_npc_msgs/srv/RequestGuiding \
  "{event_id: 'demo-g-$(date +%s)', customer_id: 'demo', preferred_table: 'T01', party_size: 1}" >/dev/null
sleep 3
wait_mode idle 30 || true
sleep 2

# 5. engaging — 모객 stack 진입 8s 후 수동 idle (override_priority)
echo "$(elapsed) [5/6] engaging → 모객 BT 진입"
set_mode engaging '{}' true
sleep 8
echo "$(elapsed)        engaging → 수동 idle 복귀"
set_mode idle '{}' true
sleep 3

# 6. emergency_stop — ALARM dwell + 자동 복귀
echo "$(elapsed) [6/6] emergency_stop → ALARM"
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: 'abort_trigger', weight: 0.9, reason: 'demo'}" >/dev/null
sleep 7
echo "$(elapsed)        alarm dwell 만료 → 자동 NORMAL"
sleep 3

echo "==================================================="
echo "$(stamp) 데모 시나리오 종료 (총 $(( $(date +%s) - T0 ))s)"
echo "==================================================="
