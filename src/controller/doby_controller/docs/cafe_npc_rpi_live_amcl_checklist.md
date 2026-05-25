# 실물 RPi 라이브 진행 — AMCL 검증 + 영상 촬영 점검 리스트 및 작업 계획

> 작성: 2026-05-17 (sim AMCL drift fundamental 한계 확정 후)
> 본 작업 목적: sim 우회 → 실 lidar + 실 카페 배치에서 AMCL 안정 검증 + 영상 촬영
> 선행 회고: `docs/daily/2026-05-17_amcl_drift_sim_diagnosis.md`
> 관련 메모리: [[project_amcl_drift_sim_limitation]] [[project_cmd_vel_safety_pipeline]] [[project_dds_wifi_multicast]] [[feedback_no_rpi_when_team_working]] [[feedback_rpi_backup_before_change]] [[feedback_daily_backup_routine]]

---

## 0. 진입 조건 (절대 — 모두 충족 시만 진행)

- [ ] **§0-A 해제 신호** — 팀 (송민규/류재상/김진우/김덕현/안순혁) 작업 종료 + 본인 명시 ("RPi 사용 OK"). 묵시적 해제 X. [[feedback_no_rpi_when_team_working]] 참조.
- [ ] **RPi 전원 ON + 네트워크 가능** — `ping -c 3 192.168.0.138` 응답.
- [ ] **RPi SSH 가능** — `ssh vic@192.168.0.138 'hostname'`. 불가 시 작업 보류 ([[feedback_daily_backup_routine]] — RPi SSH 불가 시 작업 보류).
- [ ] **PC 측 patch 영구 적용 상태 확인** — `git status` clean 또는 5 patches 만 변경. `git log -1` 으로 본 회고 commit 있는지.
- [ ] **일일 백업 완료** — `~/backup/moca_daily_<오늘날짜>/laptop/` + `rpi/` 둘 다. CLAUDE.md §7 패턴.

## 1. 사전 점검 — PC + RPi 자산 정합

### 1.1 PC 측 (sim 전용 5 patches 가 실 환경에 미치는 영향)

| Patch | 적용 위치 | RPi 라이브 영향 | 조치 |
|---|---|---|---|
| A — `recovery_alpha_fast/slow: 0.0/0.0` | `src/moca_navigation/params/nav2_params.yaml` | 실 환경에도 적용. recovery 끄기 = lidar 노이즈 시 wrong jump 회피. 실 wheel slip 시 약함 — 검증 필요. | 일단 sim patch 유지, 라이브 검증 |
| B — `do_beamskip: true` | 동상 | Nav2 표준 권장. 실에서도 OK. | 유지 |
| C — init covariance 작게 | `scripts/run_nav2_sim.sh` (sim only) | RPi 라이브에선 RViz 수동 init 또는 별 launch — 영향 X | 무시 |
| D — PGM 가구 19개 추가 | `maps/mapv5_mocamap.pgm` | **실 카페 운영 시 가구 정확 위치 다를 가능성** — scan match 잘못된 매칭 위험 | 결정: 가구 cleanup 된 backup (`maps/old/mapv5_mocamap_before_furniture_addition_20260517.pgm`) 또는 SLAM 재실행 |
| E — yaml self-init only | `scripts/run_nav2_sim.sh` (sim only) | 라이브에선 RViz 수동 / dashboard init — 무관 | 무시 |

### 1.2 RPi 측 nav2_params 동기화 결정

- `src/shared/vic_pinky/vicpinky_navigation/params/nav2_params.yaml` (RPi 빌드 측, **현 별 SoT**)
- PC `src/moca_navigation/params/nav2_params.yaml` (PC 빌드 측, 본 세션 patch 적용된 곳)

**확인 필요**: RPi bringup 이 어느 yaml 사용하는가? 
- RPi 측이 `vicpinky_navigation/params/nav2_params.yaml` 자체 사용 → PC patches A+B 가 RPi 에 미적용. 동기화 필요.
- 또는 분리 정책 (PC 가 PC nav2, RPi 는 자체) → 각각 별도 튜닝.

**확인 명령** (RPi 측):
```bash
ssh vic@192.168.0.138 'cat /opt/ros/jazzy/share/vicpinky_navigation/params/nav2_params.yaml 2>/dev/null | grep -E "recovery_alpha|do_beamskip" | head'
```

결과에 따라:
- A+B 미적용 → RPi 측 yaml 도 같이 patch. RPi 콜콘 rebuild + restart.
- 분리 정책 → RPi 측 단독 튜닝 결정.

### 1.3 PGM 결정 — 라이브 운영 시 어느 map 사용?

- **현 PGM** (`maps/mapv5_mocamap.pgm`, 본 세션 D patch 가구 추가) → sim 전용 추정.
- **Backup PGM** (`maps/old/mapv5_mocamap_before_furniture_addition_20260517.pgm`) → 라이브 운영용 (가구 cleanup, 벽만).
- **SLAM 재실행 PGM** → 실 카페 가구 정확 반영 (필요 시).

라이브 시작 시 결정:
- 일단 backup PGM 으로 시작 (실 카페 가구 위치 불확실 시 가장 안전)
- AMCL drift 발생 시 SLAM 재실행 검토 (scripts/run_slam.sh 등 — 별 작업)

`run_nav2_sim.sh` 또는 RPi bringup launch 의 `map:=` arg 로 지정 가능. PC 측 launch 가 어느 map 우선 사용하는지 확인 필요 (현 default: `find-pkg-share moca_navigation/../../../maps/mapv5.yaml` — yaml 자체는 `mapv5_mocamap.yaml` 이라 PGM 동일).

라이브용 별 yaml 만들기 권장:
```bash
cp maps/mapv5_mocamap.yaml maps/mapv5_mocamap_live.yaml
# image 필드 → mapv5_mocamap_before_furniture_addition_20260517.pgm 또는 별 PGM
# launch 시 map:=/home/gjkong/physical-ai-repo-3/src/controller/doby_controller/maps/mapv5_mocamap_live.yaml
```

---

## 2. RPi 백업 (변경 전 필수, [[feedback_rpi_backup_before_change]])

```bash
mkdir -p ~/backup/moca_daily_<오늘날짜>/rpi
# RPi → laptop 으로 백업 (RPi 디스크 절약)
ssh vic@192.168.0.138 'dpkg -l | grep -E "ros-jazzy|nav2|amcl"' \
  > ~/backup/moca_daily_<오늘날짜>/rpi/dpkg_list.txt

ssh vic@192.168.0.138 'cd ~/<RPi workspace>; git log -1; git status' \
  > ~/backup/moca_daily_<오늘날짜>/rpi/git_state.txt

ssh vic@192.168.0.138 'cd ~/<RPi workspace>/src; tar czf - vic_pinky scripts config' \
  > ~/backup/moca_daily_<오늘날짜>/rpi/rpi_src_$(date +%Y%m%d).tar.gz

# /etc/ros2 또는 환경 변수 파일 사본
ssh vic@192.168.0.138 'cat ~/.bashrc' > ~/backup/moca_daily_<오늘날짜>/rpi/bashrc.txt
```

README.md 작성:
```bash
cat > ~/backup/moca_daily_<오늘날짜>/README.md <<EOF
백업 시점: $(date)
사유: RPi 라이브 진행 (AMCL 검증 + 영상 촬영)
PC git sha: $(cd ~/physical-ai-repo-3/src/controller/doby_controller && git rev-parse HEAD)
RPi 호스트: vic@192.168.0.138 (DOMAIN=22)
네트워크: $(ping -c 1 192.168.0.138 | grep ttl)
EOF
```

---

## 3. DDS / DOMAIN 환경 설정 ([[project_dds_wifi_multicast]])

### 3.1 PC 측

```bash
# 시뮬 모드 (DOMAIN=99 + LOCALHOST_ONLY=1) 종료
bash ~/physical-ai-repo-3/src/controller/doby_controller/scripts/stop_sim.sh

# 라이브 모드 환경
export ROS_DOMAIN_ID=22
unset ROS_LOCALHOST_ONLY  # multicast 사용 안 함 → STATIC_PEERS 강제
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET  # ROS_LOCALHOST_ONLY deprecated 대체
export ROS_STATIC_PEERS=192.168.0.138  # RPi IP

# Wi-Fi multicast 차단 환경에서 unicast 강제 ([[project_dds_wifi_multicast]])
```

### 3.2 RPi 측

```bash
ssh vic@192.168.0.138
# RPi .bashrc 에 영구 설정되어 있을 가능성 — 확인
grep -E "ROS_DOMAIN|ROS_STATIC|ROS_AUTO" ~/.bashrc

# 필요 시 추가 (PC IP — 192.168.0.154 또는 본인 노트북 IP)
export ROS_DOMAIN_ID=22
export ROS_STATIC_PEERS=192.168.0.154  # PC IP
```

### 3.3 토픽 가시성 검증 (PC → RPi)

```bash
ros2 topic list | head  # /scan, /odom, /battery_state 가 보여야 함
ros2 topic hz /scan     # 5Hz 정상
ros2 topic echo --once /battery_state  # voltage + percentage
```

토픽 안 보이면:
- `ros2 daemon stop && ros2 daemon start`
- 양쪽 환경 변수 재확인
- 방화벽 (ufw status) — DDS UDP 7400~7500 port 열림
- Wi-Fi vs 유선 LAN — 유선 권장 (multicast 안정)

---

## 4. RPi bringup 순서

### 4.1 RPi 측 (vic_pinky bringup)

```bash
ssh vic@192.168.0.138
cd ~/<RPi workspace>
source install/setup.bash
ros2 launch vicpinky_bringup vicpinky.launch.xml
```

또는 PC 의 `scripts/run_teleop_ui.sh` step 3 자동 SSH bringup (현재 §0-A 차단 정책 — 사용자 명시 해제 시만).

bringup 토픽 검증 (RPi 또는 PC 양쪽):
- `/scan` 5Hz
- `/odom` 50Hz+
- `/battery_state` 1Hz
- `/joint_states` 10Hz+
- `/tf` map → odom → base_link (AMCL 시작 후)

### 4.2 PC 측 (Nav2 + dashboard)

```bash
cd ~/physical-ai-repo-3/src/controller/doby_controller
# Nav2 stack (DOMAIN=22 + 라이브 map)
ROS_DOMAIN_ID=22 ros2 launch moca_navigation bringup_launch.xml \
  map:=/home/gjkong/physical-ai-repo-3/src/controller/doby_controller/maps/mapv5_mocamap_live.yaml \
  use_sim_time:=False

# Dashboard (별 셸)
ROS_DOMAIN_ID=22 bash scripts/run_dashboard.sh --domain=22
```

또는 `run_real.sh` 통합 스크립트 (있다면 — 확인 필요).

---

## 5. AMCL 라이브 초기화

### 5.1 Robot 위치 확인

- Robot 가 실 dock 위치 (vicpinky_home, 카페 NE 코너) 에 있는지 시각 확인.
- 또는 cafe_layout.yaml `pinky_home` (-36.903, 2.693, yaw=-π/2) 부근.

### 5.2 /initialpose 발행 (RViz 또는 명령)

**옵션 A — RViz 수동 (가장 안전):**
1. RViz 띄움: `ros2 launch moca_navigation nav2_view.launch.xml use_sim_time:=False`
2. `2D Pose Estimate` 버튼 클릭
3. Map 에서 robot 실 위치 + yaw 방향 클릭/드래그
4. AMCL pose 자동 init

**옵션 B — 명령:**
```bash
QZ=$(python3 -c "import math; print(math.sin(-1.571/2))")
QW=$(python3 -c "import math; print(math.cos(-1.571/2))")
ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: -36.903, y: 2.743, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: $QZ, w: $QW}}, covariance: [0.05, 0, 0, 0, 0, 0, 0, 0.05, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.005]}}"
```

(C patch 의 작은 covariance — sim 에서 사용한 값 그대로 라이브에 적용)

### 5.3 AMCL pose vs robot 실 위치 확인

```bash
ros2 topic echo --once /amcl_pose
# Robot 실 위치 (테이프자 또는 floor marker 측정) 와 비교. 오차 < 0.3m 면 OK.
```

dashboard floorplan 마커 위치 + 실 robot 위치 시각 비교.

---

## 6. 검증 시나리오 (영상 촬영 전 단계별)

### 6.1 단계 1 — 정적 stability (5분)

- Robot 가만히 두고 AMCL pose 5분 관찰. drift 발생 안 해야 함.
- sim 에선 motion 시작 직후 drift 발생 — 실에선 다를 가능성. 확인.

### 6.2 단계 2 — 수동 teleop (10분)

- RViz teleop 또는 dashboard 의 ARROW 버튼으로 robot 1m 전후/회전.
- AMCL pose 가 robot 동작 따라 매끄럽게 update 되는지.
- yaw flip / mirror basin 진입 없는지.

### 6.3 단계 3 — NavigateToPose 단발 T01 (10분)

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: -37.12, y: 0.543, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: $QZ, w: $QW}}}}"
```

**성공 기준:**
- Goal SUCCEEDED + robot 실제 T01 (-37.12, 0.543) 부근 도달 (오차 0.3m)
- AMCL pose vs robot 실 위치 일치 (시각 + 측정)
- cmd_vel chain 정상 (controller_server 가 cmd_vel 발행, zlac_driver 가 motor 구동)

**실패 시:** §11.3 의 다른 경로 (cartographer, deeper patches 등) 로 escalate.

### 6.4 단계 4 — patrol 5 테이블 sweep (15분)

Dashboard `POST /mode patrol` 또는:
```bash
curl -X POST http://localhost:8800/api/v1/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"patrol","override_priority":true}'
```

5 테이블 (T01~T05) sweep + dwell + home 복귀. 자동 종료 (idle).

### 6.5 단계 5 — 영상 촬영 시 시나리오 (사용자 결정)

추천 시나리오 — 5 모드 자동 (이전 `scripts/run_demo_scenario.sh` 활용):
- patrol 120s → serving (T01) 38s → guiding 12s → engaging 10s → emergency_stop 5s

`scripts/record_demo.sh` (ffmpeg x11grab) — dashboard + Gazebo 화면 녹화. 라이브 시 dashboard 만 (Gazebo 없음). 실 카메라 별 (핸드폰/거치 카메라 — 사용자 결정).

---

## 7. 회복 절차 (문제 발생 시)

| 증상 | 진단 | 회복 |
|---|---|---|
| AMCL drift 발생 (사용자 시각) | `/amcl_pose` vs `gz pose 없음 — 실 robot 측정` | `/initialpose` 재발행 (단발 fix) |
| cmd_vel 안 흐름 | `ros2 topic hz /cmd_vel_nav /bt/cmd_vel /cmd_vel /pinky_cmd` 단계별 | 끊긴 단계 식별 + 해당 노드 재기동 |
| Nav2 path fail | `nav2.log` 의 "Failed to plan" | AMCL pose 확인 (벽 안 위치 X), 가구 충돌 회피 (실 가구 PGM 미반영 가능성) |
| 충돌 위험 | scan 0.3m 안 obstacle + robot 진행 중 | dashboard `POST /mode emergency_stop` 또는 e_stop 물리 버튼 (있다면) |
| zlac_driver 멈춤 | `/joint_states` hz 0 + battery_state 정상 | RPi `sudo systemctl restart` 또는 bringup 재기동 |
| Wi-Fi 끊김 | PC 토픽 안 보임 | LAN 유선 권장, DDS unicast 강제 ([[project_dds_wifi_multicast]]) |

긴급 종료:
```bash
ssh vic@192.168.0.138 'pkill -f vicpinky_bringup'  # RPi 즉시 정지
bash ~/physical-ai-repo-3/src/controller/doby_controller/scripts/stop_moca.sh                   # PC 정지
```

---

## 8. 작업 후 — 회고 + 메모리 갱신

### 8.1 회고 작성

`docs/daily/<날짜>_rpi_live_amcl_verification.md`:
- 본 체크리스트 각 항목 결과
- 라이브 AMCL 안정성 (sim vs 라이브 비교)
- 영상 촬영 결과 (영상 파일 위치)
- 발견된 새 issue + 해결 방안
- 다음 세션 후속

### 8.2 메모리 갱신

만약 라이브에서 AMCL 안정 확인:
- [[project_amcl_drift_sim_limitation]] 갱신 → "RPi 라이브에선 안정 검증됨" 추가
- 신규 메모리: `[[project_rpi_live_amcl_stable]]` — sim 한계 vs 라이브 강점

라이브에서도 drift 발생 시:
- [[project_amcl_drift_sim_limitation]] → "라이브에도 drift, fundamental 한계 확정"
- cartographer 등 다음 경로 우선순위 ↑

### 8.3 CLAUDE.md §10 M4+ ToDo 갱신

본 작업 결과 반영. AMCL drift 후속 [x] 표시 또는 추가 후속.

---

## 9. 영상 촬영 산출물 위치

- 영상 파일: `~/physical-ai-repo-3/src/controller/doby_controller/recordings/rpi_live_<날짜>_<시간>.mp4`
- 추천 길이: 5~10분 (각 모드 + 전체 시나리오)
- 사용자 결정: 핸드폰 촬영 vs ffmpeg x11grab vs 둘 다 (split-screen)

---

## 10. 안 되는 경우 escalation 경로

라이브 검증 실패 시 (AMCL 여전 drift):

1. **cartographer 교체** — 1~2 시간 작업. `docs/daily/2026-05-17_amcl_drift_sim_diagnosis.md` §11.3 경로 B.
2. **SLAM 재실행** — 실 카페 현 가구 배치 반영한 새 map 생성. `scripts/run_slam.sh` 등 (없으면 신규 작성).
3. **spawn 위치 변경** — sim 만 가능 (실 운영 dock NE 코너 보존). 라이브에선 의미 없음.
4. **다른 localization** — ndt_localizer 또는 robot_localization (EKF/UKF + IMU).

---

*다음 갱신: 라이브 검증 결과 반영*
