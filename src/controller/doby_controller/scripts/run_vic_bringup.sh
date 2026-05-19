#!/bin/bash
# ============================================================
# run_vic_bringup.sh — vic_pinky 본체 bringup 자동 기동 (moca 용)
# 실행: bash run_vic_bringup.sh
# 동작:
#   1) 로컬 ROS2 환경(domain=22, fastrtps) 세팅
#   2) 로봇 ping + sshpass 점검
#   3) 로봇(vic@$ROBOT_IP) SSH → vicpinky_bringup 기동 (없으면)
#   4) moca 핵심 토픽 발견 확인
#        /battery_state (SafetyCheck 입력)
#        /odom, /joint_states, /scan
#   5) /battery_state percentage 1회 echo
#   6) Nav2 action 서버(/navigate_to_pose) 존재 여부 보고
# 종료: bash stop_vic_bringup.sh [--keep]
# ============================================================

ROBOT_IP="${ROBOT_IP:-192.168.0.138}"
ROBOT_USER="${ROBOT_USER:-vic}"
ROBOT_PASS="${ROBOT_PASS:-1}"
ROBOT_DOMAIN_ID="${ROBOT_DOMAIN_ID:-22}"

echo "======================================================"
echo " vic_pinky bringup (moca)"
echo "======================================================"

# ── Step 1. 로컬 ROS2 환경 ──────────────────────────────────
export ROS_DOMAIN_ID="$ROBOT_DOMAIN_ID"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
unset FASTRTPS_DEFAULT_PROFILES_FILE
# Wi-Fi multicast 차단 회피 — RPi unicast peer 명시 (2026-05-07 follow 검증 사고).
# 노트북-RPi 같은 LAN 이지만 default DDS multicast (UDP 7400) 가 일부 Wi-Fi AP/라우터에서
# drop 됨 → discovery 실패. ROS_STATIC_PEERS 로 unicast 강제. RPi 측 시동 명령에도
# LAPTOP_IP 명시 필요.
export ROS_STATIC_PEERS="$ROBOT_IP"
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
LAPTOP_IP=$(hostname -I | awk '{print $1}')
source /opt/ros/jazzy/setup.bash

echo " ROBOT         : $ROBOT_USER@$ROBOT_IP"
echo " ROS_DOMAIN_ID : $ROS_DOMAIN_ID"
echo " STATIC_PEERS  : laptop=$LAPTOP_IP  rpi=$ROBOT_IP  (unicast, multicast 우회)"
echo "------------------------------------------------------"

# ── Step 2. 사전 점검 ──────────────────────────────────────
ping -c1 -W2 "$ROBOT_IP" >/dev/null 2>&1 || { echo " [ERROR] 로봇 ping 실패"; exit 1; }
echo " [OK]  ping $ROBOT_IP"
command -v sshpass >/dev/null || { echo " [ERROR] sshpass 미설치 (sudo apt install sshpass)"; exit 1; }

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
RSSH="sshpass -p $ROBOT_PASS ssh $SSH_OPTS $ROBOT_USER@$ROBOT_IP"
RSSH_F="sshpass -p $ROBOT_PASS ssh -f $SSH_OPTS $ROBOT_USER@$ROBOT_IP"

# ── Step 3. 로봇 bringup 기동 (없을 때) ───────────────────
echo " [INFO] 로봇 bringup 상태 확인..."
if $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null"; then
    echo " [OK]  bringup 실행 중 (재기동 안 함)"
else
    echo " [INFO] bringup 기동 (ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID)..."
    $RSSH_F "mkdir -p ~/logs && setsid nohup bash -c 'export ROS_DOMAIN_ID=$ROBOT_DOMAIN_ID; export ROS_STATIC_PEERS=$LAPTOP_IP; export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET; source /opt/ros/jazzy/setup.bash; source ~/vicpinky_ws/install/setup.bash; exec ros2 launch vicpinky_bringup bringup.launch.xml' </dev/null >~/logs/bringup.log 2>&1 &"
    sleep 8
    if ! $RSSH "pgrep -f '[v]icpinky_bringup' >/dev/null"; then
        echo " [ERROR] bringup 기동 실패 — 원격 로그(~/logs/bringup.log) 마지막 40줄:"
        $RSSH 'tail -40 ~/logs/bringup.log'
        exit 1
    fi
    echo " [OK]  bringup 기동 완료 (원격 로그: ~/logs/bringup.log)"
fi

# ── Step 4. 토픽 수신 확인 ────────────────────────────────
echo " [INFO] 토픽 수신 대기..."
ros2 daemon stop >/dev/null 2>&1
ros2 daemon start >/dev/null 2>&1

REQUIRED=("/battery_state" "/odom" "/joint_states" "/scan")
declare -A TOPIC_OK
for t in "${REQUIRED[@]}"; do TOPIC_OK[$t]=0; done

for i in $(seq 1 10); do
    TL=$(ros2 topic list 2>/dev/null)
    all_ok=1
    for t in "${REQUIRED[@]}"; do
        if [ "${TOPIC_OK[$t]}" -eq 0 ]; then
            if echo "$TL" | grep -qE "^${t}\$"; then
                TOPIC_OK[$t]=1
                echo " [OK]  $t"
            else
                all_ok=0
            fi
        fi
    done
    [ $all_ok -eq 1 ] && break
    sleep 1
done

# 미확인 토픽 경고
missing=0
for t in "${REQUIRED[@]}"; do
    if [ "${TOPIC_OK[$t]}" -eq 0 ]; then
        echo " [WARN] $t 미확인"
        missing=$((missing+1))
    fi
done

# ── Step 5. 배터리 상태 1회 echo ─────────────────────────
if [ "${TOPIC_OK[/battery_state]}" -eq 1 ]; then
    BATT=$(timeout 3 ros2 topic echo /battery_state --field percentage --once 2>/dev/null | grep -E '^[0-9]' | head -1)
    if [ -n "$BATT" ]; then
        # 0.9142 → 91.4% 형식
        BATT_PCT=$(awk -v v="$BATT" 'BEGIN{printf "%.1f", v*100}')
        echo " [INFO] 배터리: ${BATT_PCT}%  (SafetyCheck 임계 20.0%)"
    fi
fi

# ── Step 6. Nav2 action 확인 (선택, 없어도 계속) ──────────
NAV_COUNT=$(timeout 2 ros2 action list 2>/dev/null | grep -c "navigate_to_pose")
if [ "$NAV_COUNT" -gt 0 ]; then
    echo " [OK]  Nav2 action /navigate_to_pose 발견"
else
    echo " [INFO] Nav2 action 없음 (vicpinky_bringup만 — Approach BT는 dummy fallback)"
fi

# ── 결과 요약 ────────────────────────────────────────────
echo "------------------------------------------------------"
if [ $missing -eq 0 ]; then
    echo " 결과: bringup 준비 완료 ✓"
else
    echo " 결과: bringup 기동했으나 $missing 개 토픽 미확인 (위 [WARN] 참조)"
fi
echo ""
echo " 다음 단계 (선택):"
echo "   ▷ moca 노트북 트랙 시동 (워크스페이스 루트에서):"
echo "       source /opt/ros/jazzy/setup.bash"
echo "       source install/setup.bash"
echo "       ros2 launch dobi_npc_bringup dev_all.launch.py"
echo ""
echo "   ▷ 종료:"
echo "       bash $(dirname "$0")/stop_vic_bringup.sh         # bringup 종료"
echo "       bash $(dirname "$0")/stop_vic_bringup.sh --keep  # 유지 (로컬만 정리)"
echo "======================================================"
