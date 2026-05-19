# 첫 SLAM 맵 생성 + cabot 맵 경로 잔재 정리

**작업일**: 2026-05-08
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**선행 회고**: `2026-05-07_follow_live_tuning_session.md` (DDS multicast 우회 + abko 카메라 교체)
**상태**: 첫 매장 맵 `mocamap01w` 저장 완료. 저장 경로를 cabot → moca 로 이전.

---

## 0. 시작 컨텍스트

오늘 목표: vic_pinky 로 매장 SLAM 맵 첫 생성.

`scripts/run_teleop_ui.sh` 사용 — 어제 (2026-05-07) Wi-Fi multicast 우회 + HCAM01N pixel_format 정정 패치가 들어간 launcher. 다만 launcher 의 카메라 자동검출은 `Card type: *HCAM01N*` grep 인데 카메라 2 가 abko (Alcorlink `2ce3:c670`) 로 교체된 후라 미검출 → SLAM 만 할 거면 카메라 단계 통째로 skip 가능 (`SKIP_CAM=1`).

---

## 1. 발견

### 1.1 `web/teleop_server.py` 안에 `SlamRunner` 클래스 존재

`teleop_server.py:847` `class SlamRunner` — `slam_toolbox + rviz2` subprocess + `nav2_map_server map_saver_cli` 한 곳에 묶음. UI 의 SLAM Start/Stop/Save 버튼이 이 클래스로 연결됨.

→ **별도 `run_slam.sh` 띄울 필요 없음**. `run_teleop_ui.sh` 한 창에서 SLAM 시동, teleop, 맵 저장까지 끝남. (단, `run_teleop_ui.sh` 자체가 키보드 teleop 도 웹 UI 안에서 제공하므로 gnome-terminal teleop_twist_keyboard 도 불필요.)

### 1.2 맵 저장 경로가 cabot 잔재

`SlamRunner.MAPS_DIR = Path.home() / "cabot" / "maps"` — moca 마이그레이션 (Phase 0-A) 때 따라오지 못한 path. `scripts/save_map.sh` 도 동일 (`WS="$HOME/cabot"`).

오늘 첫 SLAM 시 `mocamap01w` 가 `~/cabot/maps/mocamap01w.{pgm,yaml}` 에 생성됨 — 의도와 불일치. `~/moca/maps/` 가 있어야 맞음.

### 1.3 `~/moca/maps/mapv1.{pgm,yaml}` (Apr 29) 잔재

마이그레이션 시 카피되어 들어온 듯한 cabot 시절 맵. 본 프로젝트 자산 아님 → 삭제.

---

## 2. 코드 patch

### 2.1 `cabot/web/teleop_server.py:851`

```diff
-    MAPS_DIR = Path.home() / "cabot" / "maps"
+    MAPS_DIR = Path.home() / "moca" / "maps"
```

### 2.2 `moca/scripts/save_map.sh`

```diff
-WS="$HOME/cabot"
+WS="$HOME/moca"
 MAPS_DIR="$WS/maps"
```

### 2.3 자산 이동/정리

```bash
mkdir -p ~/moca/maps
mv ~/cabot/maps/mocamap01w.* ~/moca/maps/
rm ~/moca/maps/mapv1.{pgm,yaml}
```

결과: `~/moca/maps/mocamap01w.{pgm,yaml}` (108KB pgm + 133B yaml) 단 한 자산.

---

## 3. SLAM 세션 타임라인 (오늘 1차 시동)

```
15:53:04  Teleop UI: http://localhost:8765           (uvicorn listen)
15:56:00  SLAM started (slam pid=9580, rviz pid=9581)
16:10:18  SAVE map=mocamap01w ok=True msg=저장 완료    ← 첫 매장 맵 저장
16:10:25  SLAM stopped
16:12:00  SLAM started (...)                         ← 재시도 (테스트)
16:12:15  SLAM stopped
16:12:24  SLAM started
16:14:26  SLAM stopped
16:16:01  SLAM started
16:27:43  SLAM stopped                               ← 마지막, 저장 안 함
```

총 ~14분 매핑 (15:56 → 16:10) 으로 한 매장 한 바퀴. 카메라 SKIP — LiDAR + odom 만으로 매핑.

---

## 4. 다음 일정 / 후속

### 4.1 cabot 잔재 추가 정리 후보 (이번 세션 외)

- `scripts/run_slam.sh` `WS="$HOME/cabot"` — UI 안에서 SLAM 가능하므로 사용 빈도 낮음. 우선순위 하.
- `scripts/run_teleop_ui.sh` `WS="$HOME/cabot"` — `cabot/install/setup.bash` source. UI 의 vicpinky_navigation launch 가 cabot 워크스페이스 거 사용 중 — moca 워크스페이스로 통일하려면 한 번에 옮겨야 함 (별도 회고 단위).
- `cabot/web/teleop_server.py` 자체 — 본질적으로 moca 자산. `~/moca/web/` 으로 이전 검토 필요. **단 큰 변경**: vicpinky_emotion 자산, 페르소나 face_avatar, 포트, .venv 의존성 모두 path 갱신 필요.

### 4.2 `run_teleop_ui.sh` 카메라 자동검출 abko 대응

`Card type: *HCAM01N*` grep 패턴이 abko 환경에서 즉사. 두 가지 옵션:
- **(A)** 패턴 확장: `*HCAM01N*|*Alcorlink*|*USB 2.0 Camera*` (다중 카메라 라인업 동시 지원)
- **(B)** USB ID 기반 검출로 전환: `lsusb` → vendor:product (`0c45:6367` / `2ce3:c670`) → `/sys/.../video*` 매핑

오늘 세션은 `SKIP_CAM=1` 우회로 통과했으나, 다음에 카메라 영상까지 UI 에 띄울 때 필수.

### 4.3 맵 검증

`mocamap01w.pgm` 시각 검증 (rviz 로 띄워서 매장 윤곽 확인) — 매핑 중 회전 / 사각지대 / 폐쇄루프 품질 확인 후 v2 매핑 여부 결정. CLAUDE.md §6 Phase 1 W2 "Approach Nav2 Action Client" 진입 전 안정 맵 1 장 확보 목표.

### 4.4 메모리 갱신 검토

기존 `project_camera_architecture.md` 는 카메라 변경 잘 추적됨. 신규 메모리는 불필요 — 본 회고 (cabot path 잔재 + moca/maps SoT) 만으로 충분. SLAM 워크플로우 (`run_teleop_ui.sh` 한 창에서 모두 처리) 는 CLAUDE.md §9 "자주 쓰는 명령어 모음" 에 한 줄 추가 검토 가능.

---

## 5. 메모

- SKIP_CAM=1 우회는 SLAM 만 할 때 매우 깔끔. LiDAR 만으로 매핑 충분.
- UI 의 SLAM Start/Stop/Save 버튼 동작 양호. 4 회 시동/정지 모두 race 없음.
- 모터 fail / E-Stop / USB power 사고 0 건 — 어제 (2026-05-07) 인프라 보강이 이번 세션 안정성 기여. (vic_pinky 본체 충전 + ROS_STATIC_PEERS 패치 효과.)
