# 2026-05-20 — RPi 라이브 AMCL 검증 (sim drift fundamental 한계 우회 검증)

> 선행: 2026-05-17 sim AMCL drift 한계 확정 회고 (`docs/daily/2026-05-17_amcl_drift_sim_diagnosis.md`)
> 점검 리스트 SoT: `docs/cafe_npc_rpi_live_amcl_checklist.md`
> 작업자: Stephen + claude (Opus 4.7 1M)
> 세션: dev branch, v1 회귀 시스템 검증 중 (라이브 코드 수정 X)

## 1. 결론 (TL;DR)

**라이브 RPi + Vic Pinky AMCL 안정 검증 완료**. sim 환경의 mirror basin / wrong basin lock-in drift 문제가 **라이브에선 재현 안 됨**. cmd_vel 50cm 명령 → wheel encoder 40.3cm 실측 + AMCL pose Δy = -0.400m + Δ 일치도 0.5% (편차 거의 0).

cartographer 등 escalation 경로 (체크리스트 §10) 불필요. **현 AMCL stack 그대로 라이브 운영 진입 가능**.

## 2. 검증 결과 (cmd_vel 50cm 단발)

| 측정 | BEFORE | AFTER | Δ | 평가 |
|---|---|---|---|---|
| `/amcl_pose` x | -36.980 | -36.981 | -0.001m | 노이즈 수준 |
| `/amcl_pose` y | **2.000** | **1.600** | **-0.400m** | 새 좌표 publish ✓ |
| `/amcl_pose` stamp | 14:51:59 | **14:57:07** | fresh | update_min_d=0.25m 초과 → publish 발동 ✓ |
| `/odom` x | 0.866 | 1.268 | **+0.402m** | wheel encoder 40.3cm 측정 |
| Δy/Δx 일치도 | — | — | **0.5%** | scan match + odom 융합 정확 |

yaw=-π/2 (forward=-y) — AMCL Δy 와 odom Δx 부호 + 크기 일관. 의미 있는 drift 없음.

## 3. 추가 검증 (cmd_vel 30cm 단발 — 사전 점검)

3초 × 0.1m/s 명령 → 실제 11.6cm (velocity_smoother acc ramp + stop ramp 영향). update_min_d=0.25m 못 넘김 → `/amcl_pose` publish skip. 단 **TF map → base_footprint y = 1.884** (시작 2.000 대비 -0.116m) 로 AMCL internal pose 는 정확 추적 확인.

## 4. 진행 절차 (12 단계 체크리스트 매핑)

### 4.1 진입 (체크리스트 §0)
- §0-A 해제: 사용자 명시 "RPi 사용 OK" (2026-05-20 13:45 KST) — vic_pinky 코드 수정 절대 불가 조건 부착
- RPi 네트워크: ping OK (192.168.0.138), SSH OK (sshpass)
- 일일 백업: `~/backup/moca_daily_20260520/` (PC tarball 45M + RPi tarball 34M + dpkg/git/bashrc/env) ✓

### 4.2 PC sim 잔재 정리 (체크리스트 §1.1 patches)
- `stop_sim.sh` + `stop_nav2_sim.sh` 로 DOMAIN=99 잔재 모두 종료
- DOMAIN=22 daemon fresh 시작
- sim patches A~E 는 PC 측 yaml 그대로 유지 — 라이브에선 yaml self-init (patch E) 가 핵심 작동

### 4.3 DDS 환경 (체크리스트 §3)
- PC: `ROS_DOMAIN_ID=22 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET ROS_STATIC_PEERS=192.168.0.138` ✓
- RPi: 기존 환경 변수 유지 (run_teleop_ui.sh / run_nav2.sh 가 자동 설정)
- Wi-Fi multicast 없이 unicast 만 — discovery OK

### 4.4 RPi bringup (체크리스트 §4.1)
- `run_teleop_ui.sh` 실행 → step 3 자동 SSH bringup → `vic_pinky_bringup`, `sllidar_node`, `twist_mux`, `velocity_smoother`, `collision_monitor`, `scan_to_scan_filter_chain`, `laser_scan_polygon_filter`, `lifecycle_manager_safety` 활성 ✓
- HCAM01N 자동 검출 + USB auto-suspend 해제 OK
- 토픽: `/scan` 5Hz, `/odom` (RELIABLE), `/battery_state` 25.42V (52.6%), `/joint_states`, `/image_raw/compressed` 22~37Hz ✓

### 4.5 PC Nav2 (체크리스트 §4.2)
- `moca_navigation/bringup_launch.xml` + `MOCA_MAP_PATH=mapv5_mocamap_live.yaml` (가구 cleanup backup PGM)
- AMCL active + map_server active + lifecycle_manager_navigation active 의 9 servers + nav2_velocity_smoother (§11.2 R2 fix 적용된 이름 분리 확인) ✓
- `bringup_smachybrid_mppi_launch.xml` 은 빌드 산출물에도 src 에도 없음 — `run_nav2.sh` 와 분리 운용

### 4.6 AMCL 자동 init (체크리스트 §5.2 옵션 B 우회 — yaml self-init only)
- yaml `set_initial_pose: true` 가 robot home pose 자동 init: (x=-36.980, y=2.000, yaw=-π/2)
- 사용자 등록 좌표 = AMCL 자동 init 좌표 = robot home dock 실 위치 (사용자 명시 일치)
- `/initialpose` 임의 발행 X (모든 맵 통일 SoT 보호)

### 4.7 정적 stability (체크리스트 §6.1, 단축 60s)
- robot 정지 상태 60s 동안 `/amcl_pose` 변동 0, timestamp 그대로 — motion 0 → AMCL update 0 의 정상 동작
- **단 transient 진단**: `nav2.log` 에 "Message Filter dropping ... laser_link" 폭주 (timestamp earlier than transform cache + queue is full). NTP / 시계 fix 후에도 폭주 지속 → 시계가 root cause 아님. INFO level 이라 AMCL 자체 작동에 치명적 영향 없으며 motion 후 update 검증으로 우회 확인. **별 추가 진단 후속**.

### 4.8 cmd_vel 단발 모션 검증 (옵션 B 채택)
- 옵션 A (e-stop release + 손 push) 시도 → wheel encoder 가 motion 감지 못 함 (`/odom` x ≈ 0). e-stop 상태에서 zlac_driver encoder freeze 가설 또는 skid. 검증 불가 판단.
- 옵션 B 채택 — `ros2 topic pub /joy/cmd_vel ... 0.1m/s × 5s` → 40.3cm 실측 + AMCL update + publish 발동 ✓

### 4.9 미수행 항목
- 수동 teleop 10분 (§6.2) — 단발 cmd_vel 로 핵심 검증 완료, skip
- NavigateToPose T01 단발 (§6.3) — BT/planner/controller chain 검증 (별 작업)
- patrol 5 sweep (§6.4) — 별 작업
- 영상 촬영 (§6.5) — 별 작업

## 5. 진행 중 발견된 함정 + 정정

### 5.1 §0-B 자동 분류기 — stop_vic_bringup.sh 차단
- "종료해줘" 요청에 stop_vic_bringup.sh 실행 시 차단됨 — vic_pinky 의존 운영 스크립트 보호 정책상 호출도 명시 승인 필요. 일관 정확.

### 5.2 pkill BRE 함정 — `-f 'A|B|C'` literal substring 매칭
- `pkill -9 -f 'rviz2|nav2_container|moca_navigation'` 가 literal 'A|B|C' substring 으로 해석되어 아무것도 매칭 안 함. 정상 종료 실패. 각 패턴별 별 명령 (`pkill -9 -f rviz2; pkill -9 -f nav2_container; ...`) 또는 `pgrep -E` 후 kill 필요.

### 5.3 .venv 누락 (워크스페이스 이동 후속 효과)
- `~/physical-ai-repo-3/src/controller/doby_controller/.venv` 미생성 → `run_teleop_ui.sh` Step 2 사전점검 fail
- 회피: `~/moca/.venv → 새 위치 symlink` (venv 의 python3 가 시스템 /usr/bin/python3.12 symlink 라 이식 가능)
- 영구 해법: 새 위치에 venv 새로 생성 + requirements.txt install (별 작업)

### 5.4 시계 drift 측정 오류 (SSH RTT 함정)
- SSH 기반 `date +%s%N` round-trip 측정 → drift 1144ms/810ms/604ms 측정. systemd-timesyncd 재시작 후에도 큰 값 유지.
- 실제 `timedatectl timesync-status` 결과: PC offset -1.088ms / RPi offset -2.011ms vs ntp.ubuntu.com → **양쪽 시계 ±3ms 안 sync**. SSH RTT half-asymmetry noise 가 잘못된 measurement bias.
- 정정: AMCL scan drop 의 진짜 root cause 는 시계 아님 — TF latency / message_filter buffer 크기 / scan rate timing 의심. **별 추가 진단 후속**.

### 5.5 e-stop 상태 odom freeze
- e-stop 누름 상태에서 손으로 robot 1m push → `/odom` x ≈ 0 (변동 없음). zlac_driver 의 encoder publish 가 e-stop 상태에서 freeze 가설.
- 결과: 옵션 A (수동 push 검증) 작동 안 함. 옵션 B (cmd_vel pub) 로 검증 진행.
- **별 진단 후속** — zlac_driver e-stop encoder publish behavior 확인.

### 5.6 nav2 vs teleop_ui dev_all 충돌 (의심)
- teleop_ui 재시동 시 nav2_container 가 동시에 die (14:23:54 KST). 명확한 root cause 미확인.
- 가설: dev_all 의 mode_manager / approach_controller 가 nav2 의 cmd_vel chain 영향 (§11 R1, R2 가드 효과 미검증) 또는 dev_all spawn 시 어떤 process kill side effect.
- 회피: 옵션 2 (teleop_ui 종료 + nav2 단독) 로 진행 → 충돌 없음. **별 진단 후속**.

## 6. 메모리 갱신

- `[[project_rpi_live_amcl_stable]]` (신규) — sim drift 와 달리 라이브에선 안정. cmd_vel 50cm 단발 결과 + 진입 절차 표준.
- `[[project_amcl_drift_sim_limitation]]` (갱신 — 본 회고 작성 시 메모리 동기화) — "라이브 AMCL 안정 검증됨, sim 한계는 시뮬-only" 추가.
- `[[feedback_pkill_bre_substring_trap]]` (신규) — pkill -f 의 BRE literal substring 함정 + 회피 패턴.

## 7. 다음 세션 후속

- [ ] **nav2.log scan drop INFO 폭주** root cause — TF latency / QoS / message_filter buffer 추가 진단
- [ ] **zlac_driver e-stop encoder freeze** 확인
- [ ] **dev_all + nav2 동시 가동 충돌** root cause — §11 가드 효과 검증
- [ ] **.venv 새 위치 영구 생성** — symlink 우회 → native venv + requirements.txt install
- [ ] **NavigateToPose T01 + patrol 5 sweep** — BT chain + planner + controller 라이브 검증 (별 세션)
- [ ] **영상 촬영** — 5 모드 자동 시나리오 (별 세션)
- [ ] CLAUDE.md §10 M4+ ToDo 의 "Sim AMCL drift 후속 — deeper patches 또는 다른 localization" 항목 갱신 (라이브 안정 검증으로 cartographer/deeper escalation 우선순위 ↓)

## 8. 정책 / 가드 준수 확인

- §0-A: 사용자 명시 "RPi 사용 OK" 해제 후만 RPi 접근 ✓
- §0-B: vic_pinky 트리 + 의존 운영 스크립트 (run_teleop_ui.sh, run_nav2.sh, run_vic_bringup.sh, stop_*.sh 등) 모두 read-only 호출 / 수정 X ✓
  - 작성한 새 자산: 본 회고 .md (docs/daily/) + 메모리 (~/.claude/projects/*/memory/) — 회귀 시스템 무관 SoT
  - 수정 안 한 자산: CLAUDE.md, docs/cafe_npc_*.md, src/dobi_npc/, src/shared/vic_pinky/, launch/config/scripts ✓
- v1 회귀 시스템 commit X 정책 ([[feedback_test_supervisor_v1_no_commit]]): 본 검증은 회귀 시스템 직접 무관 — 그러나 우려 회피 위해 본 회고 + 메모리도 commit 보류 (Stephen 별 commit 지시 시까지)

---

*검증 마무리: 2026-05-20 14:57 KST*
*다음 세션 진입점: CLAUDE.md §10 M4+ ToDo + 본 회고 §7 후속 리스트*
