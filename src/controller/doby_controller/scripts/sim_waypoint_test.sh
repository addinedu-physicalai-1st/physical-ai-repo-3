#!/usr/bin/env bash
# sim_waypoint_test.sh — mapv6 가제보에서 W1..W5 경로(T02) end-to-end 재현 테스트.
#   gazebo(새 월드) → Nav2(SmacPlanner2D+MPPI, sim time) → HOME 재로컬라이즈 → costmap clear
#   → dispatcher → "T02" → 완료/실패(+backup 리커버리) 대기 → 결과 보고.
# 도메인99 격리. 각 stack 은 setsid 로 분리해 스크립트 종료 후에도 유지.
# NOTE: set -u 금지 — ROS setup.bash 가 AMENT_TRACE_SETUP_FILES 미설정 참조함.
WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WP="$WS/config/waypoints_mapv6_capture.yaml"
source /opt/ros/jazzy/setup.bash
source "$WS/install/setup.bash" 2>/dev/null
export ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1
cd "$WS" || exit 1
rm -f /tmp/gz.log /tmp/nav.log /tmp/disp.log

echo "[1] gazebo (새 월드)..."
setsid ros2 launch moca_gazebo launch_mapv6.launch.xml >/tmp/gz.log 2>&1 &
timeout 45 ros2 topic echo /clock --once >/dev/null 2>&1 || { echo "FAIL: /clock 안뜸 (gazebo)"; exit 1; }
echo "    /clock OK"
timeout 20 ros2 topic echo /scan --once >/dev/null 2>&1 && echo "    /scan OK" || echo "    /scan 지연"

echo "[2] Nav2 (SmacPlanner2D + MPPI, use_sim_time)..."
setsid ros2 launch moca_navigation bringup_smac_mppi.launch.xml use_sim_time:=True >/tmp/nav.log 2>&1 &

# [3] initialpose 를 기동 직후부터 '지속' 발행 (순서가 핵심).
#   이 AMCL 설정은 initialpose 를 받기 전엔 map->odom TF 를 안 내보낸다.
#   그런데 nav 라이프사이클은 기동 직후 global_costmap 을 활성화하려고 map->base TF 를 기다리므로,
#   활성화 창(수십 초) 안에 initialpose 가 없으면 costmap activation 이 타임아웃 -> 전체 bringup abort
#   -> bt_navigator 비활성 -> 모든 경로 goal 거부. (원 스크립트가 /amcl_pose 를 먼저 기다린 게 버그:
#   initialpose 전엔 /amcl_pose 자체가 안 떠서 [2]에서 영구 정지.)
#   따라서 launch 와 동시에 12회(1Hz) 발행해 AMCL 활성 직후 곧바로 map->odom 이 떠 costmap 이 활성화되게 한다.
echo "[3] /initialpose HOME (8.3065,-5.6187,yaw -1.5675) 초기-지속 발행 (12x@1Hz)..."
ros2 topic pub --times 12 --rate 1 /initialpose geometry_msgs/msg/PoseWithCovarianceStamped "{header: {frame_id: map}, pose: {pose: {position: {x: 8.3065, y: -5.6187, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: -0.706168, w: 0.708044}}, covariance: [0.25,0,0,0,0,0,0,0.25,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.0685]}}" >/dev/null 2>&1 &
echo "    nav 라이프사이클 활성화 대기 (Managed nodes are active, 최대 90s)..."
timeout 90 grep -m1 "Managed nodes are active" <(tail -n0 -f /tmp/nav.log) >/dev/null 2>&1 \
  && echo "    Nav2 active OK" || { echo "FAIL: Nav2 활성화 실패 — /tmp/nav.log 확인"; exit 1; }

echo "[4] costmap clear (smac_mppi 튜닝값 inflation 0.5 그대로 — costmap↔MPPI critic 일치)..."
ros2 service call /global_costmap/clear_entirely_global_costmap nav2_msgs/srv/ClearEntireCostmap "{}" >/dev/null 2>&1
ros2 service call /local_costmap/clear_entirely_local_costmap nav2_msgs/srv/ClearEntireCostmap "{}" >/dev/null 2>&1
echo "    완료"

echo "[5] dispatcher (waypoints + use_sim_time)..."
setsid ros2 launch dobi_npc_bringup mode_serving.launch.py waypoints_yaml:="$WP" use_sim_time:=True >/tmp/disp.log 2>&1 &
timeout 20 ros2 topic echo /serving/state --once >/dev/null 2>&1 && echo "    dispatcher OK" || echo "    dispatcher 지연"

echo "[6] TF 버퍼 안정 대기 후 T02 전송..."
timeout 6 ros2 topic echo /clock --once >/dev/null 2>&1
timeout 6 ros2 topic echo /amcl_pose --once >/dev/null 2>&1
ros2 topic pub --once /serving/goto_table std_msgs/msg/String "{data: T02}" >/dev/null 2>&1
echo "    T02 전송"

echo "[7] 결과 대기 (완료/포기, 최대 220s)..."
timeout 220 grep -m1 -E "완료 — 마지막 웨이포인트|포기 \(idle\)" <(tail -n0 -f /tmp/disp.log) || echo "    (TIMEOUT 220s)"

echo "[8] 최종 위치 (목표 W05 = 5.73,-9.85):"
timeout 8 ros2 topic echo /amcl_pose --once 2>/dev/null | grep -A2 "position:" | grep -E "x:|y:" | sed 's/^/    /'
echo "[9] dispatcher 경로/리커버리 로그:"
grep -E "route goal|경로|recovery|backup|완료|실패|포기" /tmp/disp.log | tail -14 | sed 's/^/    /'
echo "DONE"
