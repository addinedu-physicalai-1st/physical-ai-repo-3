# 2026-05-29 — scout 일원화 follow 재설계 (제자리회전·후진 해소) + 실차 검증

작업자: 공국진(Stephen) · 환경: PC + 실물 vic_pinky(RPi 192.168.0.138, DOMAIN=22) · 브랜치 **`feat/scout-unified-follow` (off origin/dev, 미커밋·미푸시)**

세션 결과: 어제(2026-05-28) 실차 추종 실패(제자리회전·후진)를 **brainstorm→spec→plan→subagent 구현→실차 검증**으로 해결. **회전 추종은 실차 검증 완료(제자리회전·후진·반대회전 전부 해소).** 거리(전진) 추종은 튜닝 진행 중.

---

## 1. 배경

- 2026-05-28 실차: 구 `scout_follow_bridge`(servo bearing→합성 bbox)→follow_controller 통합이 **①제자리 회전 ②후진**으로 실패. 근본원인: scout PTZ 가 추종 루프 안 + 서보/차체 결합 + 거리 소스 부재.
- 최종 목표 = (C) 완전 추종(라포 최고 손님). 전체 비전: person_tracking→track_id→얼굴 ReID(customer_id)→감정 스코어→블랙리스트→max 선택→추종. ReID/스코어는 무거워 **Phase-1 = follow 실행/제어**만.

## 2. 설계 (스펙/플랜)

- 스펙: `docs/superpowers/specs/2026-05-29-scout-unified-follow-design.md`
- 플랜: `docs/superpowers/plans/2026-05-29-scout-unified-follow-phase1.md`
- 승인된 결정: **(I) scout 일원화**(획득·추적 모두 scout 한 카메라, association 0) + **(B) scout_cam 얼굴 임베딩**(나중) + **(2) 집중형 신규 컨트롤러**.
- 아키텍처: 손들기 획득(call_detector) → person_tracking(@`/scout_cam/image_raw`) track_id+bbox → 신규 `scout_follow_controller`: 각속도=bbox cx, 선속도=bbox 높이(bh, 후진금지) → `/follow/cmd_vel`. **추종 중 서보 freeze**(call_detector 비활성)로 PTZ 루프 밖.

## 3. 구현 (subagent-driven, TDD)

- 신규 `mobility_controller/scripts/scout_follow_controller_node.py` — 순수함수 7개(cx_to_angular, bh_to_linear, yaw_from_quat, handoff_servo_pan, handoff_done, select_target_track, next_state) + `ScoutFollowController` FSM(SEARCH→HANDOFF→FOLLOW→LOST). **단위테스트 26 passed.**
- 신규 `test/test_scout_follow_control.py`, `launch/scout_unified_follow.launch.py`. `CMakeLists.txt`/`package.xml` python install 추가.
- person_tracking 은 launch arg `input_topic:=/scout_cam/image_raw` 로 scout 영상 사용(코드 무수정). **PersonTrack.bbox=float32[4][x1,y1,x2,y2]** 파싱.
- dev 기준 정합: 브랜치를 origin/dev(e5b2737) 기준 재설정(feat/mapv6 미커밋 작업은 stash 보존). dev 에 person_tracking_pkg/mobility_controller/msg 이미 존재.

## 4. 빌드 함정 (해결)

- `dobi_npc_msgs` 를 `--symlink-install` 로 빌드 시 **`Could not import rosidl_typesupport_c`** (interface 패키지 symlink-install 함정) → person_tracking 죽음. **해결: `rm -rf build/install dobi_npc_msgs && colcon build --packages-select dobi_npc_msgs` (symlink 없이).** (오버레이 충돌 아님 — AMENT_PREFIX_PATH 깨끗 확인.)
- person_tracking_pkg 는 repo-root 에 빌드(`colcon build --packages-select person_tracking_pkg`) → 단일 `install/setup.bash` 로 전부 source.

## 5. 카메라 식별 (교훈)

- **scout PTZ = "USB 2.0 Camera"(Alcorlink 2ce3:c670) = /dev/video0** (by-id `usb-Alcorlink_Corp._USB_2.0_Camera-video-index0`). 노트북 얼굴캠 = "HD Webcam"(Bison) = /dev/video4.
- **`/dev/videoN` 번호 신뢰 X** — USB 재열거로 바뀜. 어제 doc 의 `--device=/dev/video4` 가 오늘은 노트북캠이었음. 구동 전 항상 `v4l2-ctl --list-devices`/by-id 확인. (메모리 `camera-identify-by-id`.)

## 6. 검증

### 6.1 벤치 (PC, DOMAIN=99, 차체 없음)
- 체인 작동, 회전 추종(cx→w 센터링), **후진 없음**(v≥0).
- **발견·수정: `/call/enable` QoS** — 컨트롤러 pub volatile vs call_detector sub transient_local → enable=false 미전달 → 서보 안 멈춤 → cx 출렁. **수정: latched(TRANSIENT_LOCAL) pub.** 이후 `call=stopped`(서보 freeze) 정상.

### 6.2 실차 (DOMAIN=22, 배터리 25.4V/52%)
- ✅ **closed-loop 회전 수렴+정지** — 사람 off-center → 회전 → 중앙 정렬되면 w→0 **정지. 제자리회전 없음.** `angular_sign=+1` 확정.
- ✅ **후진 없음** (bh 포화 v=0).
- ⚠ **"끝으로 가면 반대 회전"** — 진단: HANDOFF base 회전(handoff_sign 미검증)이 사람 반대로 돔. **수정: `handoff_base_w=0`(핸드오프 회전 제거, FOLLOW cx제어가 회전 담당) + `handoff_timeout_sec=0.5`.**
- ⚠ **트랙 상실 brittle** — 빠른 이동 시 BoT-SORT track_id 재할당 → SEARCH 빠짐(재손들기 필요). **수정: FOLLOW 에서 타깃 사라지면 화면 내 최근접 track 자동 재획득, tracks 있으면 SEARCH 안 빠짐.**
- ✅ **재검증(수정 후)**: cx 68~600 가로질러도 `call=stopped` 유지하며 정방향 회전·중앙수렴·정지, **반대회전 사라짐.** 프레임 완전 이탈 시 SEARCH sweep→정상 재획득.

### 6.3 거리(전진) — ✅ 성공
- **bh 포화 측정**: 2m=**1.00**(포화), 3m=**0.77**. → ~2.5m 이상에서만 거리 신호 존재(근접캠 세로FOV 한계).
- 실측 범위에 맞춰 **재튜닝: `target_bh=0.85`(≈2.4m 유지), `bh_stop=0.95`(≈2m 미만 = 너무 가까움 정지).**
- **결과: 사람이 3m+ 물러나면(bh<0.85) 로봇이 전진(v>0)으로 추종 → ~2.4m 유지. 사용자 "잘 움직여" 확인.** 후진 없음 유지. **풀 (C) 추종(회전+전진) 실차 검증 완료.**

### 6.4 발견·수정: `/call/enable` latched 교착 (중요)
- **증상**: follow만 재기동(scout 유지) 시, 사람 있어도 SEARCH에 갇힘(`call=stopped`, 추종 안 함).
- **원인**: 죽은 이전 컨트롤러가 발행한 **latched(TRANSIENT_LOCAL) `/call/enable=false`** 가 DDS에 잔존 → call_detector 계속 비활성. 새 컨트롤러는 SEARCH 시작인데 `enable=true`를 *전이 시에만* 발행(시작 시 미발행) → 영구 비활성 → lock 못 받음.
- **수정**: SEARCH 중 **항상 `enable=true` 발행**(stale latched 해소). 이후 `call=searching`→손들기→`locked`→FOLLOW(tid 잡힘) 정상.
- 진단법: FSM 상태 로그(throttle 1Hz) 임시 추가 → `st=SEARCH->SEARCH call=stopped` 로 즉시 규명. **(이 디버그 로그는 커밋 전 제거 예정.)**

## 7. 현재 상태

- **라이브 가동 중**: RPi bringup(DOMAIN=22) + scout(video0) + follow(target_bh=0.85) + 프로브. **풀 추종(회전+전진) 동작 확인됨.**
- 코드 수정 5건 **반영+빌드+실차검증 완료**: ①`/call/enable` QoS latched ②handoff_base_w=0(+timeout 0.5) ③트랙상실 자동재획득 ④target_bh=0.85/bh_stop=0.95 ⑤SEARCH 항상 enable=true(latched 교착 해소).
- ✅ 진단용 FSM 상태 로그 제거 완료 (재빌드 + 26테스트 통과). **코드 커밋 준비됨.**
- ✅ 원클릭 운영 스크립트: `scripts/start_scout_follow.sh`(일괄 시작) + `scripts/stop_scout_follow.sh`(일괄 종료·disarm) + `scripts/completion.bash`(탭완성).
- 브랜치 `feat/scout-unified-follow` (off dev) **미커밋·미푸시**. 커밋/푸시는 사용자 직접.

## 8. 다음

- [x] **전진 검증 완료** — 3m+ 물러나면 전진 추종, ~2.4m 유지. "잘 움직여" 확인.
- [x] **디버그 상태 로그 제거 + 재빌드 완료.**
- [ ] 좋으면 커밋(아래 명령) + `git push -u origin feat/scout-unified-follow` → dev PR.
- [ ] (개선) 거리 신호가 ~2.5m 이상에서만 살아있음(근접캠 한계). 더 넓은 추종범위 원하면 **Astra depth**(dev `run_tracking.sh`) 또는 `/scan` 전방 섹터로 거리소스 보강.
- [ ] (개선) HANDOFF 재설계 — off-axis 획득 시 정상 co-rotation(현재는 handoff_base_w=0으로 회피). handoff_sign 라이브 확정.
- [ ] 대기: scout 7701→moca_opserver(8800) 대시보드 통합, 노트북 캠 GEVA 감정분석, ReID customer_id(P0).

## 9. 변경 파일 (미커밋)

```
신규: mobility_controller/scripts/scout_follow_controller_node.py
      mobility_controller/test/test_scout_follow_control.py
      mobility_controller/launch/scout_unified_follow.launch.py
      doby_controller/docs/superpowers/specs/2026-05-29-scout-unified-follow-design.md
      doby_controller/docs/superpowers/plans/2026-05-29-scout-unified-follow-phase1.md
      doby_controller/docs/daily/2026-05-29_scout_unified_follow.md (본 문서)
수정: mobility_controller/CMakeLists.txt, package.xml
(scout_reactor 별 repo: 어제 /call/state 변경 등 기존 미커밋)
```

## 10. 후반 — 지그재그 튜닝 차단 원인 규명 (공유 DOMAIN 22 스택 충돌)

지그재그 게인 비교 튜닝(Config A: kp_angular 0.25/deadband 60 vs B: angular_gain↑) 진입 시 차량이 우리 명령과 무관하게 움직임 → 원인 추적.

**발견: DOMAIN 22(팀 공용)에 정규 moca engaging 스택이 제3의 머신에서 가동 중.**
- `ros2 node list` (DOMAIN 22): `/approach_controller_node`, `/group_approach_node`, `/mode_manager`, `/geva_node`, `/persona_manager`, `/dialog_router`, `/rapport_tracker_node`, `/person_tracking_node`, `/robot_cam/usb_cam`.
- **이 노트북 아님**(local pgrep 깨끗) + **RPi 아님**(pgrep 깨끗) → 제3 머신(팀원 PC).
- **충돌 메커니즘**: `approach_controller` → `/bt/cmd_vel` **priority 80**. 우리 `scout_follow_controller` → `/follow/cmd_vel` **priority 50**. twist_mux 가 80 을 우선 → 그 머신 스택이 살아있는 한 우리 추종 명령이 차량에 미도달. **지그재그 튜닝 불가의 근본 원인.**

**자동 실행 여부 조사 (사용자 질의):**
- OS 레벨 자동시작 **없음** — 이 노트북에 moca/ros/scout systemd·cron·`~/.config/autostart` 항목 0.
- `mode_manager`: **자동 실행 아님** — 명시 런처(`dev_all.launch.py`/`dev_common.launch.py` = `run_teleop_ui` step 4d)로만. `moca_opserver` 는 SetMode **클라이언트**일 뿐 spawn 안 함.
- `approach_controller`: **단독 자동 아님** — `mode_manager` 가 `SetMode('engaging')` 받을 때 `mode_engaging.launch.py` 로 spawn.
- 유일한 자동 구동 요소 = 로컬 `moca_opserver`(8800)의 `idle_patrol_timer`(`patrol_enabled` 기본 True → idle 5분 후 자동 `SetMode('patrol')`) + `completion_watcher`(dwell 후 자동 `idle`). **patrol 만 자동, engaging 아님.** → 지금 뜬 engaging 스택은 자동 타이머가 아니라 그 머신에서 명시적으로 engaging 트리거된 것.
- 사용자 판단: "정상적인 모드" (rogue 아님, 정규 funnel/engaging).

**조치/결정:**
- 로컬 스택 + RPi bringup 은 `stop_scout_follow.sh` 로 완전 종료(local 깨끗, RPi disarm, 7701 free). `moca_opserver`(8800)도 종료됨.
- 사용자가 로컬·RPi 다 종료했으나 **DOMAIN 22 engaging 스택은 그대로 잔존**(제3 머신, 여기서 못 끔, §0-A).
- **방향 전환(사용자 명시)**: "다른 것은 실행하지 않도록 할게" + **"scout_follower 기반 추종부터 정확하게 수행"에 집중.** 지그재그/full-vision 후속은 그 다음.
- **차단 조건**: 그 팀원 PC 에서 engaging 스택(`mode_manager` → `SetMode('idle')` 또는 런처 종료)이 내려가 DOMAIN 22 가 scout+follow 만 남아야 깨끗한 추종 테스트 가능.

## 10.5 이미지 토픽 일원화 — `/robot_cam/image_raw` (방향 (나), 2026-05-29 후반)

팀원이 카메라 입력을 팀 표준 `/robot_cam/image_raw` 로 ROS 전송하도록 변경 → 우리 follow 도 정합.

**조사 결과 — `/scout_cam/image_raw` 에 묶인 노드 (2 레포 + apt 분산):**
- `~/scout_reactor`(`scout_reactor` pkg): `call_detector_node`(lock-on), `palm_gesture_node`, `scout_servo_node`(간접) + `palm.launch.py`. (`omx_reactor` pkg: `scout_dashboard_node` — annotated 구독, 간접).
- 메인 레포: `person_tracking_node`(`person_tracking_pkg`@doby_controller), `scout_follow_controller`(`mobility_controller`, 간접 — tracks 구독).
- apt `/opt/ros/jazzy`: `scout_cam`=`v4l2_camera_node`(발행부, 소스X·launch remap만). person_tracking `use_compressed=true` → `<input>/compressed` 구독.

**채택 = (나): scout_reactor 무손상 + relay 로 토픽명만 통일.**
- 신규 `mobility_controller/scripts/scout_image_relay_node.py` — `/scout_cam/image_raw[/compressed] → /robot_cam/image_raw[/compressed]` 미러(raw+compressed). `topic_tools` 미설치라 apt 의존 없이 자작(단일 카메라 grab 유지, 토픽명만 복제).
- `scout_unified_follow.launch.py`: `scout_image_relay` 노드 추가(`relay_scout_image` 기본 true) + person_tracking 입력 기본값 `/scout_cam/image_raw → /robot_cam/image_raw`. 통합 모드(팀이 직접 발행)면 `relay_scout_image:=false`.
- `CMakeLists.txt`: relay install(PROGRAMS, RENAME scout_image_relay).
- **scout_reactor `palm.launch.py` 무수정** — call_detector/palm_gesture 는 `/scout_cam/image_raw` 그대로 → lock-on 무손상.
- 검증: 빌드 OK, 실행체 설치 OK, launch 인자 OK, relay 기동 시 `/robot_cam/image_raw`+`/compressed` 생성 확인(벤치 DOMAIN=99).
- 미검증: 실제 영상 흐름(scout 카메라 연결 후) + 통합 시 팀 발행과 이중 publish 회피(relay_scout_image:=false).

## 10.6 거리제어 = 라이다 전방거리 전환 (1.5m 추종, 2026-05-29 저녁 실차)

bbox-height 거리제어의 한계 + 해결.

**문제:** scout PTZ 세로FOV 가 좁아 **bh(bbox높이)가 ~2m 이내 전부 1.0 으로 포화** → 거리 정보 소실. 실측: 사람이 3m 에 서 있어도 bbox 가 프레임 세로를 꽉 채워 bh≈0.99. → `err=target_bh−bh<0` + `bh≥bh_stop` 둘 다 전진 0 → 로봇이 "이미 가깝다" 오판하고 멀리(3m) 유지. **bh 로는 1.5m 추종 불가(포화).**

**해결: 전진/거리 소스를 라이다 `/scan_filtered` 로 교체** (회전은 cx 유지).
- 신규 순수함수 `dist_to_linear(scan_dist, target_dist, kp, max_v, deadband)` — 전진 전용(목표보다 가까우면 0, 후진 절대 금지, None/무효 0).
- 신규 `front_min_range(ranges, angle_min, angle_inc, forward_rad, half_rad, rmin, rmax)` — 정면(forward_rad) ±half 섹터 유효 최근접. **각도차 판정 → ±π 랩어라운드 안전.**
- 컨트롤러: `/scan_filtered`(sensor_data QoS) 구독 → `_on_scan` 가 정면섹터 최근접을 `self.scan_dist` 로. FOLLOW 에서 `distance_source=='scan'` 이면 `dist_to_linear` 사용.
- 신규 파라미터(전부 live-tunable): `distance_source`(scan|bbox), `target_dist`(1.5), `kp_dist`(0.6), `dist_deadband`(0.1), `scan_forward_deg`, `scan_front_deg`(30), `scan_min_range`(0.25), `scan_range_max_follow`(5.0).

**라이다 정면 오프셋 보정 (핵심 함정):** vicpinky 라이다는 **angle 0 가 로봇 정면이 아님** — 실측상 전체 스캔 최근접이 angle 0 엔 없고 ~180° 에 존재. **로봇 정면 = 라이다 180°.** → `scan_forward_deg=180.0` (launch). 0° 로 두면 전방섹터에 아무것도 안 잡혀 전진 영구 0.

**실차 검증:** "2m 라이더 직진·회전 잘 동작" 확인. 전진-only + 정면±30° + collision_monitor 백업으로 보수적 동작.

**속도 튜닝(라이브 +10%):** `max_angular` 0.3→0.315→**0.331**, `max_linear` 0.22→0.231→**0.243** (각 5%씩 2회). launch 기본값 반영.

**단위테스트:** `dist_to_linear` 7 + `front_min_range` 5 신규 추가(후진금지·포워드오프셋180·섹터필터·랩어라운드).

## 11. 다음 세션 이어받기 (핸드오프) — 다음 테스트 = "scout_follower 추종 정확화"

**결정된 다음 테스트:** 지그재그/full-vision 은 보류. **scout_follower 기반 추종(회전+전진 closed-loop)을 깨끗한 환경에서 정확하게 재검증** 하는 것이 최우선. (사용자 명시: "scout_follower 기반 추종부터 정확하게 수행할 수 있도록 집중.")

**진입 전 전제조건 (순서대로):**
1. **DOMAIN 22 청소 확인** — 팀원 PC engaging 스택이 내려갔는지. 확인:
   ```bash
   export ROS_DOMAIN_ID=22 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_STATIC_PEERS=192.168.0.138 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
   source /opt/ros/jazzy/setup.bash
   ros2 node list   # /approach_controller_node, /mode_manager 등 없어야 함 (있으면 /bt/cmd_vel@80 가 우리 follow@50 덮어씀 → 테스트 불가)
   ```
   → 잔존 시 그 머신에서 `SetMode('idle')` 또는 런처 종료 필요 (여기서 못 끔, §0-A).
2. **§0-A RPi 접근 재확인** — 사용자 "RPi 사용 OK" 명시 받기 (묵시 해제 X).
3. **카메라 by-id 확인** — scout PTZ = "USB 2.0 Camera"(Alcorlink). `start_scout_follow.sh` 가 by-id 자동탐지하나 구동 후 7701 영상이 scout 인지 육안 확인 (노트북캠 video4 아님).

**테스트 시작 명령:**
```bash
bash /home/gjkong/physical-ai-repo-3/src/controller/doby_controller/scripts/start_scout_follow.sh
# (벤치: --bench  / 종료: stop_scout_follow.sh)
```
→ 손들기 → call lock-on → person_tracking track → `/follow/cmd_vel` → 회전+전진 추종.
**검증 포인트:** ① 회전 closed-loop 수렴·정지(제자리회전 X) ② 후진 X ③ 3m+ 물러나면 전진(bh<0.85), ~2.4m 유지 ④ 트랙 상실 시 자동 재획득. (모두 5/29 검증된 동작 — 깨끗한 DOMAIN 에서 재현 확인.)

**추종 정확화 완료 후 후속(순서):**
- (a) 지그재그 게인 비교 튜닝: Config A(kp_angular 0.25/deadband 60) vs B(angular_gain↑0.8/dead_zone↑0.10). `ros2 param set /scout_follow_controller ...` 라이브 (set_parameters_callback 구현됨).
- (b) 커밋: 브랜치 `feat/scout-unified-follow` (off origin/dev) **미커밋** — 사용자 직접 add/commit/push (커맨드만 제시).
- (c) 대기: scout 7701→moca_opserver(8800) 대시보드 통합, 노트북캠 GEVA 감정, ReID customer_id(P0).

**현재 상태 스냅샷 (저녁 갱신):** 팀 스택은 팀원 PC 재시작으로 정리됨, DOMAIN 22 깨끗. **scout follow 라이브 가동 중**(RPi bringup 클린 재기동 후 베이스 구동부 정상 — 처음엔 반쪽 bringup 으로 휠드라이버 미가동이라 안 움직였음, stop_vic_bringup→run_vic_bringup 로 해결). **회전 + 라이다 기반 1.5m 거리추종 실차 동작 확인**("2m 직진·회전 잘 동작"). 토픽 일원화(relay→/robot_cam/image_raw), 라이다 정면=180° 보정, 속도 +10%(0.331/0.243) 적용. 단위테스트 38(기존26+신규12). 테스트 일시정지(e-stop + 배터리 충전 중). 코드 변경 미커밋(6a25054 이후 scan 거리제어분).

---

*관련 메모리: project_scout_follow_bearing_behavior, camera-identify-by-id, follow-two-features-disambiguation, customer-reid-p0-pending, project_team_domain22_engaging_collision.*
