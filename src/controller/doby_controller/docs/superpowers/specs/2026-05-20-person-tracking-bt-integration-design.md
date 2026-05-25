# 2026-05-20 — person_tracking ↔ 모객 BT funnel 통합 (Phase 2 후속)

> 작성: 2026-05-20 (doby) | 트랙: 모객 (engaging) | 상위 phase: Phase 2 W4 후속
> 학술 근거: Layer 1 (Isla 2005) / Layer 5 (Marzinotto 2014) 변경 없음

---

## 1. 한 줄 정의

팀원이 머지한 `person_tracking_pkg` (YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose)
출력을 모객 BT funnel 의 **stage 1 IdleScan** 과 **stage 2 Approach** 로 흡수해서,
노트북 단독 환경에서 `IdleScan → Approach → IceBreak → Minigame → Offer → LeadIn`
한 사이클을 토픽 흐름 + cmd_vel echo 수준까지 검증한다.

---

## 2. 동기 — 왜 지금 이걸 하는가

| 발견 | 의미 |
|---|---|
| BT `IdleScan` 가 dummy SUCCESS (사람 인식 미연결) | 모객 funnel 의 진입 신호가 없음. 늘 즉시 stage 2 진입 |
| BT `Approach` 는 `/customer_pose` 를 **map 미터 좌표** + Nav2 액션 가정 | TF + AMCL + Nav2 모두 의존. 노트북 단독 검증 불가 |
| `person_tracking_node` → `/customer_pose` 는 **픽셀 정규화 (0~1)** + `z = bbox 높이 비율` | 같은 토픽 이름, 의미 충돌 |
| `approach_controller_node` 가 PD 제어로 `/bt/cmd_vel` 직접 발행 | BT 와 무관하게 평행 동작 중. BT funnel 의 다른 stage (IceBreak/Minigame) 와 연계 없음 |
| `group_approach_node.min_group_size=2` | solo 손님 무시. 사용자 결정 "1명 이상 = 모객 대상" 과 모순 |

→ 두 트랙(BT funnel ↔ person_tracking)을 **하나의 funnel 안으로 흡수**해서
모객 BT 의 전체 사이클이 노트북 단독으로 굴러가게 한다.

---

## 3. 결정 사항 (사용자 확정)

| # | 결정 사항 | 채택 |
|---|---|---|
| D1 | Approach 구조 | **BT 게이트 + controller 유지** — BT 가 `/approach/enable` Bool 토글로 controller 의 cmd_vel 발행을 ON/OFF |
| D2 | 카메라 | **노트북 내장 (카메라 1, /dev/video0)** + `v4l2_camera_node` 1단 마스터 → GEVA / person_tracking 둘 다 토픽 구독 |
| D3 | IdleScan SUCCESS 판정 | tracks.size ≥ 1 가 **N=5 프레임 연속 안정** + customer_id 출력 (top track_id = 가장 큰 bbox 사람) |
| D4 | Approach SUCCESS 판정 | `/customer_pose.z (bh) ≥ 0.6` 가 **M=5 프레임 연속 안정** |
| D5 (도출) | approach_target 선정 | **`group_approach_node` 그대로** + `min_group_size=1` override — D3 (1명 이상 모객) 과 정합 위해 도출 |

---

## 4. 아키텍처

### 4.1 데이터 흐름 (정상 호객 1 사이클)

```
[하드웨어]
  /dev/video0 (노트북 내장 카메라 1)
       │
       ▼
[v4l2_camera_node "webcam_master"]           ← dev_common.launch.py 에 신규 추가
       │  /webcam/image_raw (sensor_msgs/Image, 30Hz, BGR8 640x480)
       │  /webcam/image_raw/compressed (CompressedImage)
       ├──────────────────────────┐
       ▼                          ▼
[geva_node]                  [person_tracking_node]
  input_topic=/webcam/...     input_topic=/webcam/...
   /geva/state (V,A)           /person_tracking/tracks (PersonTrackArray)
                               /customer_pose (PoseStamped, 픽셀 정규화)
                                          │
                                          ▼
                              [group_approach_node]
                                min_group_size=1 (override)
                                /person_tracking/approach_target (Int32)
                                          │
                                          ▼
                              [approach_controller_node] ← patch: /approach/enable 게이트
                                /bt/cmd_vel (Twist, priority 80 → twist_mux)
                                          │
                                          ▼
                                   [vic_pinky RPi]
                                  (라이브 시 모터 회전, 노트북 단독 시 echo 만)

[BT funnel — mode_engaging stack]
  SafetyCheck → EmotionMonitor → cafe_funnel:
    IdleScan      구독: /person_tracking/tracks         → SUCCESS + customer_id
    Approach      발행: /approach/enable                ← onStart True
                  구독: /customer_pose (bh) +
                         /person_tracking/tracks (lost) → SUCCESS / FAILURE
                  발행: /approach/enable                ← onHalted/끝나면 False
    IceBreak → Minigame → Offer → LeadIn (기존 그대로)
```

### 4.2 인터페이스 정의

| 토픽 | 타입 | 발행 | 구독 | 주기 / 의미 |
|---|---|---|---|---|
| `/webcam/image_raw` | sensor_msgs/Image | webcam_master | geva_node, person_tracking_node | 30Hz, BGR8 640x480 |
| `/webcam/image_raw/compressed` | sensor_msgs/CompressedImage | webcam_master | person_tracking_node | use_compressed 경로 |
| `/person_tracking/tracks` | dobi_npc_msgs/PersonTrackArray | person_tracking_node | IdleScan, Approach, group_approach_node | 10-30Hz |
| `/customer_pose` | geometry_msgs/PoseStamped | person_tracking_node | Approach, approach_controller_node | 픽셀 정규화 (x=cx/W, y=cy/H, z=bh) |
| `/person_tracking/approach_target` | std_msgs/Int32 | group_approach_node | approach_controller_node | -1=없음, ≥0=group_id |
| **`/approach/enable`** | **std_msgs/Bool** | **BT Approach** | **approach_controller_node** | **신규 — onStart True / 종료 False** |
| `/bt/cmd_vel` | geometry_msgs/Twist | approach_controller_node | twist_mux | priority 80 |

### 4.3 BT Approach 노드 — 단순화 (Nav2 코드 제거)

```cpp
class Approach : public BT::StatefulActionNode {
  // 입력 포트
  //   bh_threshold (default 0.6)       — 종료 판정 임계 bbox 높이 비율
  //   stable_frames (default 5)        — bh 연속 안정 프레임
  //   lost_timeout_sec (default 2.0)   — tracks 빈 시간 허용
  // 출력 포트
  //   (없음 — customer_id 는 IdleScan 출력 → blackboard 통과)

  // 발행: /approach/enable (Bool)
  // 구독: /customer_pose, /person_tracking/tracks

  onStart():
    publish enable=true
    reset stable_count, last_track_seen_t

  onRunning():
    if (현재 시각 - last_track_seen_t > lost_timeout_sec)
        publish enable=false; return FAILURE
    if (bh >= bh_threshold) stable_count++ else stable_count = 0
    if (stable_count >= stable_frames)
        publish enable=false; return SUCCESS
    return RUNNING

  onHalted():
    publish enable=false
};
```

**제거되는 코드**: `rclcpp_action::Client<NavigateToPose>`, dummy goal 가드, Proxemic 계산,
`abort_threshold` 포트 (Approach 노드 자체 abort 책임은 SafetyCheck + EmotionMonitor 로 이관).

### 4.4 BT IdleScan 노드 — Stateful 로 승격

```cpp
class IdleScan : public BT::StatefulActionNode {
  // 입력 포트
  //   stable_frames (default 5)        — 사람 발견 연속 안정 프레임
  // 출력 포트
  //   customer_id (string) — top track_id (가장 큰 bbox 사람)

  // 구독: /person_tracking/tracks

  onStart():
    reset stable_count

  onRunning():
    if (tracks.size >= 1) stable_count++ else stable_count = 0
    if (stable_count >= stable_frames):
        set customer_id = top_track.track_id (string)
        return SUCCESS
    return RUNNING

  onHalted(): // no-op
};
```

### 4.5 approach_controller_node patch

```python
# 신규 구독
self._enable = False
self._sub_enable = self.create_subscription(
    Bool, '/approach/enable', self._cb_enable, 10)

def _cb_enable(self, msg):
    if not msg.data and self._enable:
        # disable 전환 시 PD 상태 reset (재진입 race 방지)
        self._prev_err_x = 0.0
        self._d_filtered = 0.0
    self._enable = msg.data

# _tick() 진입부에 게이트
def _tick(self):
    if not self._enable:
        return  # publish skip → twist_mux pose_timeout 후 하위 채널로 권한 이전
    ... 기존 로직 ...
```

---

## 5. 변경 파일 목록 + 노드 배치 정책

### 5.1 노드 배치 (always-on vs 모드 진입 시)

**원칙: 현 dev_common 의 always-on 배치 그대로 유지 + webcam_master 만 추가.**
팀원 머지(`f8fce31`)로 person_tracking 3 노드 + min_group_size=1 이 이미 always-on 적용된 상태.
YOLO 부하는 idle 에서도 발생하지만 이미 운영 결정 사항 — 부하 최적화는 별 트랙.

| 노드 | 배치 | 사유 |
|---|---|---|
| `webcam_master` (v4l2_camera_node) | **dev_common (신규 추가)** | GEVA + person_tracking 양쪽 토픽 구독자용. 카메라 1단 마스터 |
| `geva_node` (patch) | dev_common (기존) | cv2.VideoCapture → `/webcam/image_raw` 구독으로 전환 |
| `person_tracking_node` | dev_common (기존) | input_topic launch arg 로 `/webcam` ↔ `/robot_cam` 전환 가능 |
| `group_approach_node` (min_group_size=1) | dev_common (기존, 그대로) | 이미 적용 — 변경 없음 |
| `approach_controller_node` (patch) | dev_common (기존) | `/approach/enable` 게이트 추가 |
| `bt_executor` (모객 BT) | mode_engaging stack (기존) | 그대로 |
| `minigame_runner` | mode_engaging stack (기존) | 그대로 |

### 5.2 카메라 소스 전환 (use_webcam launch arg)

dev_common 에 `use_webcam:=true|false` (default true) 추가:
- `true` (노트북 단독 검증): `webcam_master` spawn + `person_tracking.input_topic=/webcam/image_raw` + `geva_node.input_topic=/webcam/image_raw`
- `false` (RPi 라이브): `webcam_master` skip + `person_tracking.input_topic=/robot_cam/image_raw` + `geva_node.input_topic=/webcam/image_raw` (geva 는 항상 노트북 카메라)

**geva 와 person_tracking 의 카메라 출처 분리**: geva 는 사용자 표정용 노트북 카메라(/webcam) 고정. person_tracking 만 `/webcam` (검증) ↔ `/robot_cam` (라이브) 전환.

⇒ `use_webcam` 분기는 `person_tracking_node.input_topic` 만 영향. `geva_node` 는 항상 `/webcam/image_raw` 구독.

### 5.3 변경 파일

| # | 파일 | 변경 종류 |
|---|---|---|
| 1 | `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/idle_scan.hpp` | 전면 개편 — Stateful + tracks 구독 + ros_node 주입 |
| 2 | `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/approach.hpp` | 전면 개편 — Nav2 제거 + enable 발행 + bh 안정 검사 |
| 3 | `src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp` | IdleScan 등록 시 ros_node 주입 매크로로 변경 |
| 4 | `src/dobi_npc/dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` | IdleScan stable_frames="5" + Approach bh_threshold="0.6" stable_frames="5" lost_timeout_sec="2.0" |
| 5 | `src/dobi_npc/person_tracking_pkg/person_tracking_pkg/approach_controller_node.py` | `/approach/enable` 구독 + 게이트 (default enable=false) |
| 6 | `src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py` | webcam_master v4l2_camera_node 추가 + `use_webcam` arg + person_tracking input_topic 분기 + geva input_topic 추가 |
| 7 | `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py` | cv2.VideoCapture → `/webcam/image_raw` 구독 + `input_topic` 파라미터 |
| 8 | `src/dobi_npc/dobi_npc_bringup/launch/mode_engaging.launch.py` | 변경 없음 (person_tracking 은 dev_common 이미 always-on) |

**파일 8 변경 → 실질 변경 7 파일** (mode_engaging.launch.py 는 변경 없음).

---

## 6. §0-B vic_pinky 트리 영향 검토

본 작업의 변경 대상은 **모두 dobi_npc / person_tracking_pkg 트리** 내부.
`src/shared/vic_pinky/` 트리 + `~/vicpinky_ws/` (RPi) + `scripts/run_vic_bringup.sh` /
`run_robot_cam.sh` / `run_teleop_ui.sh` 등 §0-B 보호 자산은 **touch 0**.

`/bt/cmd_vel` 은 vic_pinky bringup 의 twist_mux 입력 토픽 (priority 80) — 본 작업은
**발행 측 게이트** 만 추가, twist_mux/zlac_driver/collision_monitor 등 RPi 측 자산은 변경 없음.

---

## 7. 에러 처리 / 안전 매트릭스

| 상황 | 동작 |
|---|---|
| 손님 카메라 frame 밖 (tracks 0) | Approach: lost_timeout_sec 후 FAILURE → ReactiveFallback root 재진입 → IdleScan 재시작 |
| EmotionMonitor abort (사용자 anger) | ReactiveFallback emotion alarm SUCCESS → cafe_funnel halt → Approach onHalted → enable=false → controller 정지 |
| SafetyCheck alarm (배터리 / scan) | 위와 동일 (safety alarm 분기) |
| approach_controller pose_timeout (1초) | controller 자체 PD 상태 reset + publish skip (이미 구현) |
| /approach/enable race (BT 종료 직후 controller 의 마지막 tick) | controller `_enable=False` 전환 시 prev_err_x + d_filtered reset → 다음 enable=true 시 D항 튐 방지 |
| twist_mux pose_timeout (0.5초, /bt/cmd_vel) | controller 가 publish 정지하면 자동 — 본 작업 변경 없음 |
| 노트북 카메라 1 점유 충돌 (geva_node 도 동일 카메라) | v4l2_camera_node 1단 마스터 → 둘 다 토픽 구독 → 충돌 해소 |

---

## 8. 검증 (노트북 단독, vic_pinky 모터 없음)

### Phase A — 카메라 + 인식 흐름 (5 분)

```bash
moca_build && moca_activate
# 1) dev_common (webcam_master + geva + person_tracking + group_approach)
ros2 launch dobi_npc_bringup dev_common.launch.py
# 2) 별 터미널에서
ros2 topic hz /webcam/image_raw                       # ~30Hz
ros2 topic hz /person_tracking/tracks                 # 10-30Hz
ros2 topic echo /customer_pose --once                  # 카메라 앞에 서서 발행 확인
ros2 topic echo /person_tracking/approach_target --once # solo → group_id 0+ 발행 (min_group_size=1)
ros2 topic hz /geva/state                              # GEVA 가 새 입력으로 정상 동작
```

### Phase B — BT funnel 통합 (10 분)

```bash
ros2 launch dobi_npc_bringup mode_engaging.launch.py
# bt_executor + minigame_runner + person_tracking 트랙 모두 spawn

# 별 터미널
ros2 topic echo /approach/enable                # IdleScan SUCCESS 시점에 true → Approach SUCCESS 시점에 false
ros2 topic echo /bt/cmd_vel                     # enable=true 동안만 비-zero
ros2 topic echo /dialog/request                 # IceBreak 진입 시 "casual_browser" 발행

# 사용자 동작
1) 카메라 앞 거리 1.5m → IdleScan 5 frames stable → SUCCESS log
2) 가까이 (bh 0.6 이상) → Approach SUCCESS → /approach/enable=false
3) IceBreak phrase 발화 (TTS) + face_avatar 표정
4) Minigame 진입 (RPS / speed_counter)
5) Offer / LeadIn
```

### 합격 기준

- [ ] `/webcam/image_raw` 30Hz 발행
- [ ] `/person_tracking/tracks` 10Hz 이상 발행
- [ ] solo 손님 시 `/person_tracking/approach_target ≥ 0` 발행 (min_group_size=1 override 검증)
- [ ] `/geva/state` 발행 유지 (카메라 1 점유 충돌 해소 검증)
- [ ] BT IdleScan SUCCESS 가 5 frames 안정 후 트리거 (단발 frame 으로 false-positive 없음)
- [ ] BT Approach `/approach/enable=true` 발행 → `/bt/cmd_vel` 발행 시작
- [ ] bh ≥ 0.6 가 5 frames 안정 후 Approach SUCCESS → `/approach/enable=false` → `/bt/cmd_vel` 발행 정지
- [ ] IceBreak / Minigame / Offer / LeadIn 정상 진입

**모터 검증 (RPi 라이브)**: 본 spec 범위 밖. §0-A 해제 후 별 트랙.

---

## 9. 미해결 / 후속 트랙

1. **bh ↔ 실거리 캘리브**: bbox 높이 비율은 사람 키 + 자세에 의존. 노트북 카메라 1 의 화각이 운영 카메라 2 (abko) 와 달라 라이브 재튜닝 필요. → RPi 라이브 트랙 (§0-A 해제 후) 에서 처리.
2. **controller close_threshold (0.72) vs BT bh_threshold (0.6)**: BT 가 controller 보다 먼저 SUCCESS → controller 가 더 가까이 안 감 — 의도된 분리. 단 두 값의 책임 경계 재검토 후속.
3. **stage 4 Minigame 카메라 (카메라 3) 와 stage 1-2 카메라 1 의 ON/OFF 동기**: 본 spec 범위 밖. 별 트랙.
4. **person_tracking_pkg test/**: 본 작업 후 `/approach/enable` 게이트 단위 테스트 추가 후속.
5. **dwell 시간 / 페르소나별 stable_frames / bh_threshold 차등화**: persona YAML 필드 후속.
6. **multi-customer 시 BT 가 customer_id 를 따라가는지**: 본 spec 은 top track_id 한 명만 고정 — track lost 후 new track 진입 시 자연 재시작 (FAILURE → root 재진입). multi-handoff 정책은 후속.

---

## 10. 학술 정합

본 통합은 학술 청사진을 **변경하지 않는다**:

- Layer 1 (Isla 2005): BT funnel 5-stage 그대로 (IdleScan-Approach-IceBreak-Minigame-Offer 5단계 + LeadIn 6단계)
- Layer 2 (Russell 1980): EmotionMonitor abort 로직 그대로
- Layer 3 (Salichs 2014): GEVA 가 카메라 1 점유에서 토픽 구독으로 바뀐 것 외 동일
- Layer 4 (Castro-González 2016): Minigame stage 그대로
- Layer 5 (Marzinotto 2014): ReactiveFallback + Sequence 형식화 그대로 유지

학술 발표 시 본 spec 의 IdleScan/Approach 구현 디테일은 §Implementation 섹션 footnote 로 처리.

---

## 11. 관련 문서 / 메모리

- `CLAUDE.md` §0-B (vic_pinky 트리 절대 수정 금지 — 본 작업 영향 없음 검토 완료)
- `CLAUDE.md` §11 (Navigation 코드 분리 원칙 — `/bt/cmd_vel` 발행자는 controller 단일 유지, BT 는 게이트 토픽만)
- `docs/cafe_npc_paper_master.md` (학술 청사진)
- `docs/cafe_npc_camera_architecture.md` (카메라 1/2/3 SoT)
- `docs/cafe_npc_implementation_plan.md` (16 주 구현 계획)
- 메모리: [[project_camera_architecture]] [[project_cmd_vel_safety_pipeline]] [[feedback_dont_touch_working_code]]

---

*마지막 갱신: 2026-05-20 (doby) — brainstorming 5 결정 확정 후 spec 작성*
