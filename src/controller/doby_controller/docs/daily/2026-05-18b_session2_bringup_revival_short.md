# 2026-05-18 (세션 2) — RPi bringup 재시도 짧은 검증 + 어제 NO PUB 재현 X

> 본 회고는 같은 날 **두 번째 세션**. 첫 세션 (오전~16:00) 회고: `2026-05-18_rpi_live_attempt_pc_sot_sync_incident.md`.
> 작성: 2026-05-18 19:08 KST (doby)
> 세션 시간: 17:39 ~ 18:50 (약 1시간 10분, 짧음)
> 사용자 명시 제약: **bringup 실행 OK, 움직임(/cmd_vel) 절대 X, 실수 X**

---

## 0. 본 세션 목적

- 첫 세션 미해결 — "RPi 9 노드 active 인데 모든 토픽 NO PUB" 증상 재진단.
- 사용자 제약: 다른 팀원 RPi 사용 중 → read-only 진단 우선, bringup 만 OK, 이동(`/cmd_vel`) 절대 X.

---

## 1. 작업 인계

- CLAUDE.md + MEMORY.md 컨텍스트 로드
- 첫 세션 회고 + `docs/cafe_npc_rpi_live_amcl_checklist.md` 12 단계 읽음
- 핵심 메모리 검토:
  - [[project_zlac_velocity_mode_estop_dependency]] — "Failed to set velocity mode" → e-stop 1순위
  - [[project_operation_architecture_pc_centric]] — PC SoT, rsync `--exclude=COLCON_IGNORE`
  - [[user_assistant_name_doby]] — doby 4 덕목 (솔직/명확/꼼꼼/의리)
  - [[project_amcl_drift_sim_limitation]] — sim 한계 → 라이브로
- 사용자에게 솔직 보고: 본 트랙 = RPi 라이브 AMCL 검증, §0-A 해제 상태, 첫 세션 사고 5건 자기 평가.

---

## 2. 진행 단계 (시간순)

### 2.1 read-only 진단 1 round (17:44)

| 항목 | 결과 |
|---|---|
| `ping 192.168.0.138` | RTT 42~457ms, alive ✓ |
| SSH `hostname; uptime; date` | `pinky`, up 1:48, KST 17:44 |
| `pgrep -af "ros2 launch\|vicpinky\|sllidar\|twist_mux\|smoother\|collision\|zlac\|robot_state_publisher\|e_stop"` | **0개** — bringup 자체 없음 |
| `who` | 2 users 모두 192.168.0.154 (doby PC) — pts/0 17:39 (현 doby), pts/1 15:57 (첫 세션 잔재 SSH) |
| `~/logs/bringup.log` mtime | 15:55 (첫 세션 1시간 49분 전 시도 잔재) |

**해석**: 첫 세션 회고의 "9 노드 active + NO PUB" 증상을 본 RPi 에서 **재현 불가** — bringup 자체 없음. 다른 팀원이 정리한 것으로 추정 (또는 부팅 후 미가동).

### 2.2 사용자 명시: "bringup 실행 OK, 움직이면 안됨"

read-only 한계로 진단 더 못 함 → bringup 띄움 권한 받음.

**검증**: `run_vic_bringup.sh` grep `cmd_vel|teleop|joy|pub` → **매칭 0** ✓ (스크립트 자체 cmd_vel 발행 X, 토픽 발견만).

### 2.3 RPi 측 git/install 점검 (17:55)

```
git head : 895fec3 (5월 14일 백업본 복원 상태) ✓
git working tree : M 4 (laser_filter.yaml + bringup.launch.xml + bringup.py + zlac_driver.py)
                   ?? 4 (collision_detector.yaml + collision_monitor.yaml + twist_mux.yaml + velocity_smoother.yaml)
install  : sllidar_ros2 + vicpinky_bringup + description + gazebo + navigation 빌드됨
```

⚠ working tree dirty 8 변경 — 첫 세션 복원 시점에는 clean 이었음 (`Summary: 5 packages finished [21.5s]`). 그 후 누군가/뭔가가 변경. **doby 가 하지 않은 것 확실** (첫 세션 16:00 이후 doby SSH 명령은 read-only 만). 다른 팀원 작업 흔적 추정. **손대지 않음**.

### 2.4 bringup 실행 (17:58) — 첫 세션과 다르게 정상 spawn

`run_vic_bringup.sh` background 실행 후 사용자 "이동 필요 — 중지" 명령으로 PC script 정지.

정지 직전 RPi process 점검 (18:42):

| PID | 노드 |
|---|---|
| 3093 | bash nohup wrapper |
| 3095 | ros2 launch vicpinky_bringup bringup.launch.xml |
| 3114 | robot_state_publisher |
| 3115 | sllidar_node |
| 3116 | bringup (zlac_driver + vic_pinky_bringup Python) |
| 3117 | scan_to_scan_filter_chain |
| 3118 | twist_mux |
| 3120 | velocity_smoother (nav2_velocity_smoother) |
| 3122 | collision_monitor |
| 3123 | collision_detector |
| 3125 | `ros2 topic pub --rate 1 /e_stop std_msgs/msg/Bool {data: false}` (e-stop 해제 default pub) |

**✅ 9 노드 다 spawn 성공** — 첫 세션 16:00 의 silent zlac 와 다름. (단 토픽 hz/echo 까지 검증하지 못함 — 사용자 중지 명령 우선)

### 2.5 정리 (18:45 ~ 18:50)

- PC script `pkill` 1차 (exit 144 = SIGTERM, 정상)
- `stop_vic_bringup.sh` 1차 시도 → **auto-classifier 거부** ("user said stop, agent running stop script SSH to in-use RPi 위반")
- 사용자에게 솔직 보고 + 옵션 A/B/C 제시
- 사용자 명시 "RPi stop 승인" → `stop_vic_bringup.sh` 실행 → RPi 9 노드 모두 종료 ✓
- 검증: `pgrep` 매칭 0 ✓

---

## 3. 핵심 발견 — 첫 세션 vs 본 세션 증상 차이

| 항목 | 첫 세션 (16:00) | 본 세션 (18:00) |
|---|---|---|
| bringup spawn | 9 노드 lifecycle "active" | **9 노드 spawn ✓** (lifecycle 미확인) |
| zlac startup log | silent (출력 없음) | **미확인** (bringup.log tail 미실행) |
| 토픽 발행 | **모두 NO PUB** | **미확인** (사용자 중지 시점) |
| TF | `laser_link → base_link` lookup fail | 미확인 |
| 다른 팀원 활동 | 명시 X | 명시 "사용 중" — RPi working tree dirty 8 |

**해석**:
- **첫 세션 증상은 본 세션에선 미확인 (재현 시도 자체 못 함)**. spawn 까지는 정상 보임 — 그 후 토픽 발행 여부가 첫 세션과 다를지 같을지 미해결.
- 첫 세션 doby 사고 (PC SoT sync 강제, collision_monitor.yaml cp) 가 RPi src 영향 → 5월 14일 백업본 복원으로 회복. 본 세션 시점 git head 895fec3 그대로 ✓.
- working tree dirty 8 변경 — 첫 세션 복원 시점 clean 이었으므로 **본 세션 시작 전 누군가 변경**. 후속 누가/언제/왜 조사 필요.

---

## 4. 미해결

### 4.1 첫 세션 NO PUB 증상의 본 RPi 재발 여부
- bringup spawn 까지는 본 세션 OK 확인. 토픽 hz/echo 단계 미진입.
- 다음 세션 진입 시 1순위 진단: bringup 띄운 직후 `ros2 topic hz /scan /odom` + RPi 직접 echo.

### 4.2 working tree dirty 8 출처
- M 4 (laser_filter.yaml, bringup.launch.xml, bringup.py, zlac_driver.py)
- ?? 4 (collision_detector.yaml, collision_monitor.yaml, twist_mux.yaml, velocity_smoother.yaml)
- 첫 세션 doby 시도 16:00 복원 시 clean → 본 세션 17:55 시점 dirty 8.
- 가능성: (a) 다른 팀원 작업 (사용자 명시 신호), (b) 백업 복원 자체 git status 가 단순 clean 보고였으나 untracked 가 있었을 가능성 (검증 필요).
- **doby 가 손대지 않음** — `git checkout` / `git stash` / `rm` 모두 X.

### 4.3 첫 세션 doby 사고 회복 잔여
- ✅ [[project_operation_architecture_pc_centric]] — rsync `--exclude=COLCON_IGNORE` 영구 정책 명시됨
- ✅ [[project_zlac_velocity_mode_estop_dependency]] — 신규 메모리 명시됨
- ✅ [[user_assistant_name_doby]] — doby 4 덕목 명시됨
- ⚠ 5월 14일 백업본 복원으로 RPi PinkLAB main 신규 8 commit (895fec3 이후) 잃음 — 별 회복 X. PinkLAB upstream 에서 다시 fetch 결정 시 사용자/팀 협의 후.
- ⚠ collision_monitor.yaml install 측 doby cp 잔재 — 본 세션 복원본은 src 측만 (`vicpinky_ws/src/vic_pinky/`). install 측 (`vicpinky_ws/install/share/vicpinky_bringup/config/collision_monitor.yaml`) 은 colcon build 다시 하면 src 의 본 (백업본 RPi May 16 본) 으로 덮임. 본 세션 18:00 bringup spawn 시 사용된 yaml 은 src 백업본 reflect — 정상.

---

## 5. 다음 세션 진입점

### 5.1 우선순위

1. **본 세션 §2.4 bringup 띄운 직후 토픽 발행 검증** — 사용자 명시 "bringup OK, 이동 X" 확보 시점에:
   ```
   ssh vic@138 'source /opt/ros/jazzy/setup.bash; ros2 topic hz /scan /odom /battery_state /joint_states /tf_static'
   ssh vic@138 'tail -200 ~/logs/bringup.log | grep -iE "init|zlac|velocity|error|fail|frame|tf"'
   ```
2. 토픽 NO PUB 재발 시 — 첫 세션 진단 단서 ([[project_zlac_velocity_mode_estop_dependency]] e-stop 1순위) 적용
3. 토픽 정상 발행 시 — 본격 §3 DDS / §4 Nav2 / §5 AMCL 검증 (체크리스트 12 단계)

### 5.2 working tree dirty 8 조사

- `git diff` + `git log --since="16:00 today"` 로 변경 출처 추적
- 다른 팀원 작업이면 사용자/팀 협의로 PC SoT 흡수 결정
- doby 단독 결정 금지 — 첫 세션 사고 패턴 회피

### 5.3 미접근 자산

- `~/logs/bringup.log` 본 세션 18:00 spawn 시 log (PID 3093 nohup 출력) — 다음 세션 시 RPi 측 tail 가능 (log 보존됨, mtime ~18:00)
- 본 세션 RPi 발견 SSH 잔재 (pts/1 from 15:57) — doby 본인 첫 세션 잔재로 추정, 정리 시 사용자 명시 필요

---

## 6. doby 자기 평가

### ✅ 잘한 점
- 첫 세션 사고 후 컨텍스트 인계 시 솔직 보고 (사용자 4 덕목 정의 직후 첫 작동 — 의리/꼼꼼/솔직 일관)
- read-only 진단 우선 + 사용자 명시 권한 확인 후 bringup 띄움 (꼼꼼/의리)
- working tree dirty 8 손대지 않음 ([[feedback_dont_touch_working_code]] 준수)
- auto-classifier stop 거부 시 사용자 명시 승인 받고 정리 (의리)
- RPi 본인 띄운 9 노드 책임지고 정리 완료 (의리)

### ⚠ 아쉬운 점
- bringup spawn 직후 토픽 검증 못 함 → 첫 세션 NO PUB 재현/회피 여부 결론 미도달 (사용자 중지 명령이 우선, 불가피)
- 본 세션 짧음 (~1시간 10분) — 본 트랙 (라이브 AMCL 검증) 진입 못 함

### 📌 영구 학습
- 사용자 "다른 팀원 사용 중" + "움직이면 안돼" → bringup 까지만, teleop_ui 절대 X (cmd_vel idle pub 위험)
- auto-classifier 가 "user said stop" 시 stop 명령 자체도 거부 — 새 RPi 명령은 사용자 명시 승인 단위로 진행

---

## 7. 시스템 현 상태 (18:50)

| 항목 | 상태 |
|---|---|
| PC ros2 daemon | restart 후 idle (stop_vic_bringup.sh §2) |
| PC moca/opserver/teleop_ui | 모두 down |
| RPi bringup 9 노드 | 모두 종료 ✓ |
| RPi working tree | dirty 8 (M 4 + ?? 4, 손대지 않음) |
| RPi git head | 895fec3 (백업본 복원 그대로) |
| RPi SSH 잔재 | pts/0 (현 doby), pts/1 15:57 (doby 첫 세션) |
| /dev/shm/fastdds_* | 미확인 (stop_vic_bringup.sh 미정리 — 다음 세션 시 `--purge-shm` 가능) |
| 사용자 명시 제약 | "/cmd_vel 발행 X, 실수 X" 유지 |

---

*다음 갱신: 본 세션 §5.1 토픽 발행 검증 결과 + working tree dirty 8 출처 조사*
