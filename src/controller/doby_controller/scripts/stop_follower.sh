#!/bin/bash
# stop_follower.sh — 추종 시나리오 노드 전체 종료
# 사용: bash scripts/stop_follower.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_IP="${ROBOT_IP:-192.168.0.138}"

echo "[0] 기존 런치 프로세스 강제 종료..."
pkill -f "dev_common.launch\|mode_follow.launch" 2>/dev/null
sleep 1

echo "======================================================"
echo " 추종 시나리오 종료"
echo "======================================================"

echo "[1] 노트북 노드 종료..."
pkill -f "person_tracking_node"  2>/dev/null
pkill -f "group_approach_node"   2>/dev/null
pkill -f "geva_node"             2>/dev/null
pkill -f "rapport_tracker"       2>/dev/null
pkill -f "persona_manager"       2>/dev/null
pkill -f "dialog_router"         2>/dev/null
pkill -f "face_avatar"           2>/dev/null
pkill -f "tts_node"              2>/dev/null
pkill -f "mode_manager"          2>/dev/null
pkill -f "target_selector"       2>/dev/null
pkill -f "customer_identity"     2>/dev/null
pkill -f "person_detector"       2>/dev/null
pkill -f "dev_common.launch"     2>/dev/null
pkill -f "mode_follow.launch"    2>/dev/null
echo " → 노트북 노드 종료 완료"

echo "[2] RPi mobility_controller 종료..."
sshpass -p '1' ssh -o StrictHostKeyChecking=no vic@$ROBOT_IP \
    "pkill -f 'mobility_controller_node\|approach_controller_node\|follow_controller_node' 2>/dev/null; sleep 2; pkill -9 -f 'mobility_controller_node\|approach_controller_node\|follow_controller_node' 2>/dev/null; echo done" \
    2>/dev/null && echo " → RPi 종료 완료" || echo " → RPi 연결 실패 (수동 종료 필요)"

echo ""
echo " 종료 완료. 다시 시작: bash $SCRIPT_DIR/run_follower.sh"
echo "======================================================"
