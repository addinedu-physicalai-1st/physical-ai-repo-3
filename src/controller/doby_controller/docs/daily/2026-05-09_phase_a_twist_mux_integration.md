# 2026-05-09 — Phase A: twist_mux 통합 + cmd_vel 우선순위 mux

**작업자**: gjkong (Stephen)
**SoT**: `docs/cafe_npc_safety_zone.md` §4-§6 Phase A
**선행**: 2026-05-08 `safety_zone_research_and_plan.md` (조사 + 적용 계획)
**소요**: 약 4시간 (백업 + 검증 디버그 포함, 디버그 비중 ~50%)

---

## 1. 한 줄 요약

> 카페 호객 로봇의 cmd_vel 발행자(BT/follow/joy) 충돌을 명시적 우선순위 mux 로 라우팅. e_stop lock 까지 통합. 안전 영역 침입 일시정지/재개 메커니즘의 첫 인프라 확정.

---

## 2. 변경사항

### 2.1 신규 파일

| 파일 | 내용 |
|---|---|
| `src/shared/vic_pinky/vicpinky_bringup/config/twist_mux.yaml` | 4 입력 priority + e_stop lock yaml. `use_stamped: false` 명시 |

### 2.2 수정 파일

| 파일 | 변경 |
|---|---|
| `src/shared/vic_pinky/vicpinky_bringup/launch/bringup.launch.xml` | twist_mux 노드 + e_stop default-false 1Hz publisher (`<executable>`) 추가 |
| `src/shared/vic_pinky/vicpinky_navigation/launch/navigation_launch.xml` | velocity_smoother 출력 remap `cmd_vel_smoothed → bt/cmd_vel` (composable + 비-composable 양쪽) |
| `src/dobi_npc/dobi_npc_bringup/dobi_npc_bringup/follow_controller_node.py` | `cmd_vel_topic` 기본값 `/cmd_vel → /follow/cmd_vel` |
| `web/teleop_server.py` | `cmd_pub` 토픽 `cmd_vel → /joy/cmd_vel` |

### 2.3 cmd_vel 토폴로지

**Phase A 전**:
```
[BT/Nav2]      ─┐
[follow]       ─┼→ /cmd_vel → zlac_driver  (모두 같은 토픽 publish, race condition)
[teleop]       ─┘
```

**Phase A 후**:
```
[BT/Nav2 smoother out]  ─→ /bt/cmd_vel    (priority 80)  ─┐
[follow_controller]     ─→ /follow/cmd_vel (priority 50)  ─┤
[teleop_server]         ─→ /joy/cmd_vel   (priority 100) ─┼→ twist_mux ─→ /cmd_vel ─→ zlac_driver
[e_stop default pub]    ─→ /e_stop=false (lock 255 t=5s) ─┘
```

---

## 3. 검증 결과 — C.1 ~ C.5.1 전 단계 통과

| 단계 | 검증 항목 | 결과 |
|---|---|---|
| C.1 | launch syntax dry-run (`--print`) | ✓ 4 노드 정상 펼쳐짐 |
| C.2 | RPi launch 실 spawn | ✓ pgrep 5 process alive (bringup/sllidar/laser_filters/twist_mux/e_stop_default_pub) |
| C.3 | 토픽 list + 타입 | ✓ `/joy /bt /follow/cmd_vel + /cmd_vel + /e_stop`, 모두 `geometry_msgs/Twist` (use_stamped:false) |
| C.4 | twist_mux 노드 graph | ✓ Sub: 3 cmd_vel + 1 e_stop, Pub: /cmd_vel + /diagnostics |
| C.5.0 | 0값 forward (joy → /cmd_vel) | ✓ `/cmd_vel hz: 10.000` |
| C.5.3 | e_stop 차단 + 5초 timeout 자동 복구 | ✓ true 발행 시 publisher 정지, false 복귀 후 10Hz 복구 |
| C.5.2 | priority unmasked/masked 양보 | ✓ joy → bt → follow 순서로 timeout 시 mask 전환 |
| C.5.1 | 실 모터 회전 + 정지 | ✓ 모터 회전 정상 (이동 20cm, 이슈 §4 참조), 명시 0 발행 후 정지 |

---

## 4. 디버그 흔적 — 발견한 이슈 4건

### 4.1 ⚠ twist_mux 4.5.0 `use_stamped` default = true → 기존 Twist 발행자와 mismatch

**증상**: C.3 에서 `/joy/cmd_vel` 등이 `TwistStamped` 로 등록됨. 우리 발행자(follow_controller, teleop_server, Nav2 smoother) + 구독자(zlac_driver) 모두 `Twist` (unstamped) → 메시지 흐름 X.

**원인**: twist_mux 4.5.0 부터 신규 추가된 `use_stamped` 파라미터, default true.

**해결**: yaml 의 `ros__parameters` 에 `use_stamped: false` 명시. 한 줄 추가로 끝.

**교훈**: ROS2 패키지 신버전 도입 시 default 파라미터 변경 가능성 — `[INFO] "use_stamped" is not declared as parameter, defaulting to "true"` 같은 INFO 로그를 놓치지 말 것.

### 4.2 ⚠ twist_mux 4.5.0 lock default = locked → e_stop 발행자 없으면 모든 cmd_vel 차단

**증상**: C.5.0 에서 /joy/cmd_vel 발행해도 /cmd_vel 출력 0 line. `/diagnostics` 보니 `lock locks.e_stop: locked`, 모든 입력 `masked`.

**원인**: lock topic 에 메시지가 한 번도 안 오면 fail-safe 로 `locked` (이전 버전의 default unlocked 와 다름).

**해결**: 옵션 B 채택 — bringup launch 에 `<executable cmd="ros2 topic pub --rate 1 /e_stop ... data: false">` 추가. 1Hz false 발행으로 lock 해제 + 발행자 죽으면 5초 timeout 후 자동 lock (이중 fail-safe).

**교훈**:
- launch xml `<executable>` 의 cmd attribute 에서 single-quote 가 vanish — `bash -c "..."` wrapping + xml `&apos;` escape 필요. 시도 3번 후 성공.
- twist_mux 의 lock 동작은 "메시지 없을 때 = 보수적 차단" — 일관된 fail-safe 정책이지만 사전 인지 필요.

### 4.3 ⚠ ROS_DOMAIN_ID 함정 — `bash --noprofile --norc` 시 .bashrc 안 읽음

**증상**: RPi SSH 명령에서 `ros2 node list` 가 비어있음. 노트북에서는 정상.

**원인**: bringup launch 는 ROS_DOMAIN_ID=22 로 시작했는데, ssh + `bash --noprofile --norc` 셸은 `.bashrc` (ROS_DOMAIN_ID=22 포함) 읽지 않아 default 0 으로 실행 → 다른 도메인 → 노드 안 보임.

**해결**: RPi 측 검증 명령에 `export ROS_DOMAIN_ID=22 ROS_STATIC_PEERS=192.168.0.154 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET RMW_IMPLEMENTATION=rmw_fastrtps_cpp` 명시 (run_vic_bringup.sh 와 동일 환경).

**교훈**: 노트북 `run_vic_bringup.sh` 가 환경 export 까지 처리하는 반면, RPi 측 직접 명령은 환경 누락 위험. 향후 RPi 검증 스크립트 작성 시 동일 pattern 적용.

### 4.4 ⚠ zlac_driver 에 cmd_vel deadman timeout 없음

**증상**: C.5.1 실 모터 회전 검증 시 이동 거리 20cm (기대 4-5cm). 분석 결과 zlac_driver 가 cmd_vel 메시지 안 와도 last target 유지.

**원인**: `vicpinky_bringup/bringup.py` 의 `twist_callback` 은 target 갱신만, 별도 watchdog timer 없음. 30Hz `update_and_publish` timer 가 last target 으로 RPM 계속 명령.

**해결 (당장)**: Phase A 검증 스크립트는 명시 0 발행 (--times 50 = 5초) 으로 보강.

**해결 (Phase B 자동 보강)**: `nav2_velocity_smoother` 의 `velocity_timeout` + `nav2_collision_monitor` 의 `source_timeout` 이 자동으로 cmd_vel 0 강제 publish — 별도 코드 변경 없이 Phase B 진입과 동시에 해결.

**해결 (장기)**: bringup.py 에 watchdog timer 추가 PR — vic_pinky 공식 fork 에 제안 가능. 우선순위 낮음 (Phase B 가 자연스럽게 처리하므로).

**메모리 저장**: `project_zlac_driver_no_deadman.md` (영구).

---

## 5. 백업 / 롤백 자산

`~/backup/moca_phase_a_20260509/` 디렉토리에 통합:

```
laptop/
  ├── git_state.txt              moca + vic_pinky HEAD/branch/status
  ├── dpkg_pre_phase_a.txt       apt 4종 설치 후 시점 스냅샷
  ├── moca_unstaged.patch        워킹트리 미커밋 변경 21KB
  └── files/                     변경 대상 4파일 사본

rpi/
  ├── _meta.txt                  백업 시각/호스트
  ├── git_state.txt              vicpinky_ws/src/vic_pinky HEAD 895fec3
  ├── dpkg_pre_phase_a.txt       변경 전 ROS2 패키지
  ├── dpkg_post_phase_a.txt      변경 후 (twist-mux 2종 추가)
  ├── apt_install_log.txt        apt install 출력 캡처
  ├── debs/                      twist-mux + msgs deb 파일 (롤백용)
  └── files/                     RPi bringup.launch.xml 사본
```

롤백 절차 (필요 시):
```bash
# RPi 측
cp ~/backup/moca_phase_a_20260509/rpi/files/vicpinky_ws/.../bringup.launch.xml \
   ~/vicpinky_ws/src/vic_pinky/vicpinky_bringup/launch/
sudo apt remove ros-jazzy-twist-mux ros-jazzy-twist-mux-msgs
colcon build --packages-select vicpinky_bringup --symlink-install

# 노트북 측
git restore src/dobi_npc/.../follow_controller_node.py web/teleop_server.py \
            src/shared/vic_pinky/vicpinky_navigation/launch/navigation_launch.xml \
            src/shared/vic_pinky/vicpinky_bringup/launch/bringup.launch.xml \
            src/shared/vic_pinky/vicpinky_bringup/config/  # twist_mux.yaml 삭제
colcon build --packages-select dobi_npc_bringup vicpinky_navigation --symlink-install
```

---

## 6. 학술/표준 정합 재확인

본 Phase A 작업이 SoT 문서 §2 의 표준 매핑을 어떻게 채우는지:

| 표준 | Phase A 적용 |
|---|---|
| **IEC 60204-1 §9.2.2 Cat 0/1/2** | e_stop lock = Cat 1 (전원 유지 + cmd_vel 차단) 또는 Cat 2 (Monitored Standstill). 우리 구현은 Cat 2 — zlac_driver 전원 유지하고 cmd_vel 0 강제 |
| **ISO 13482 §5 (mobile servant robot)** | 안전 임계 노드(twist_mux + zlac_driver) RPi 단일 호스트 배치 — Wi-Fi 단절 시 fail-safe |
| **ISO/TS 15066 §5.5 SSM** | 이번 Phase 에서는 미적용 (Phase B 의 collision_monitor 가 적용) |
| **ISO 3691-4 (이중 영역)** | 이번 Phase 에서는 미적용 (Phase B 의 PolygonStop + PolygonSlow) |
| **ISO 13849-1 PL=d** | 미달 — ROS2/twist_mux 자체 functional safety 인증 X. 카페 환경 best-effort. SoT §7.1 의 갭 그대로 |

→ Phase A 는 **Cat 2 정지 명령 라우팅 인프라** 단계. 실 zone 검출은 Phase B+.

---

## 7. 후속 / 보강 항목

### 7.1 Phase B 진입 직전 (D+2~3)

- [ ] **velocity_smoother 설정** (`config/safety/velocity_smoother.yaml`):
  - max_velocity [0.3, 0, 1.0], max_accel [0.3, 0, 1.5] (Babel 2022 보수적), max_decel [-0.8, 0, -1.5]
  - velocity_timeout 1.0 — **zlac deadman 자동 보강 (§4.4)**
- [ ] **collision_monitor 설정** (PolygonStop 0.4×0.6m + PolygonSlow 0.7×0.9m, source `/scan`)
- [ ] **RPi launch 통합** — `twist_mux → /cmd_vel_raw → smoother → /cmd_vel_smoothed → monitor → /cmd_vel`. 현재 임시 `cmd_vel_out → cmd_vel` remap 을 `cmd_vel_raw` 로 변경 + 두 노드 추가
- [ ] **lifecycle_manager** — collision_monitor + smoother 가 lifecycle 노드. configure/activate 자동화

### 7.2 Phase B live 검증 시 점검 항목

- [ ] PolygonStop 안에 사람이 들어오면 cmd_vel 즉시 0 (BT 는 RUNNING 유지)
- [ ] PolygonSlow 안에 사람이 들어오면 0.4× 속도 감속
- [ ] Slowdown polygon 밖으로 나오면 정상 속도 복귀
- [ ] velocity_smoother 의 max_decel 적용 시 자연스러운 감속 곡선 (jerk limit)
- [ ] **§4.4 자동 보강 검증** — cmd_vel 발행자(joy/bt/follow) 모두 죽었을 때 velocity_timeout 으로 0 강제 → 모터 정지

### 7.3 Phase A 의 임시 처리 → Phase B 정식

- twist_mux output remap `cmd_vel_out → cmd_vel` (임시) → `cmd_vel_out → cmd_vel_raw` (정식)
- e_stop default-false 1Hz publisher (launch 의 `<executable>`) → 후속에서 별도 패키지 (운영 UI 의 정지 버튼이 true 발행)

### 7.4 발견한 외부 이슈 (별도 이슈 트래킹)

- **vic_pinky 양 호스트 git 상태 다름**: 노트북 `feature/dobi-npc-base` 193bb22, RPi `main` 895fec3 + bringup.py/zlac_driver.py 워킹트리 미커밋. 동기화 정책 미정. Phase A 의 `bringup.launch.xml` 변경은 scp 로 sync 처리. 정식 git 통합은 별도 결정.
- **zlac_driver deadman 추가 PR 가치**: 우선순위 낮음, Phase B 자동 보강으로 우선 해결.

---

## 8. 다음 작업

**Phase B 진입** (D+2~3):
1. `config/safety/velocity_smoother.yaml` + `config/safety/collision_monitor.yaml` 신규 작성
2. RPi launch 에 두 노드 추가 + lifecycle_manager 등록
3. 토픽 토폴로지 변경 (`cmd_vel_raw` 신설)
4. live 검증 (사람/벽 접근 시 정지/감속)
5. Phase B 회고

**Phase B 시작 시 컨텍스트**: 본 회고 + SoT `docs/cafe_npc_safety_zone.md` §6 Phase B + 메모리 `project_cmd_vel_safety_pipeline.md` + `project_zlac_driver_no_deadman.md`.

---

## 9. 메모리 갱신

| 메모리 | 갱신 내용 |
|---|---|
| 신규 `feedback_rpi_backup_before_change.md` | RPi 변경 전 dpkg+deb+git+사본 백업 정책 |
| 신규 `project_zlac_driver_no_deadman.md` | bringup.py deadman 부재 + 보강 위치 |
| 신규 `project_map_sot_mapv4.md` | 2026-05-09 SLAM SoT mapv4 갱신 |
| 갱신 `MEMORY.md` | 위 3건 인덱스 추가 |

---

*Phase A 종료. Phase B 진입 준비 완료.*
