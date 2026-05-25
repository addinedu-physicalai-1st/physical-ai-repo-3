#!/bin/bash
# ============================================================
# save_map.sh — 현재 SLAM 맵을 PGM/YAML 로 저장
# 실행: bash save_map.sh <map_name>
# 출력: $WS/maps/<map_name>.pgm + .yaml
# 전제: run_slam.sh 가 실행 중이어야 함 (slam_toolbox /map 발행 중)
# ============================================================

# 스크립트 위치 기반 워크스페이스 루트 — clone 위치 무관 작동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
MAPS_DIR="$WS/maps"

if [ -z "$1" ]; then
    echo "사용법: bash save_map.sh <map_name>"
    echo "예:    bash save_map.sh cafe_v1"
    exit 1
fi
NAME="$1"

mkdir -p "$MAPS_DIR"

export ROS_DOMAIN_ID=22
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
source /opt/ros/jazzy/setup.bash

echo "=== /map 토픽 확인 ==="
if ! ros2 topic list 2>/dev/null | grep -qE "^/map$"; then
    echo " [ERROR] /map 토픽 없음 — slam_toolbox 가 실행 중인지 확인 (run_slam.sh)"
    exit 1
fi

OUT="$MAPS_DIR/$NAME"
echo "=== 저장 → $OUT.{pgm,yaml} ==="
cd "$MAPS_DIR"
ros2 run nav2_map_server map_saver_cli -f "$NAME" 2>&1 | tail -10

echo ""
echo "결과:"
ls -la "$MAPS_DIR/$NAME"* 2>/dev/null
