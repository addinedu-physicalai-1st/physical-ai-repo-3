# 2026-05-28 — mapv6 등록 + SmacPlanner2D+MPPI 전환 + 라이브 waypoint 캡처/주행

작업자: 공국진(Stephen) · 환경: RPi 라이브(vic@192.168.0.138, DOMAIN=22) · PC(192.168.0.154)
세션 결과: **mapv6 SoT 등록 + SmacPlanner2D+MPPI 적용 + 13개 pose 캡처(W01~W12, HOME) + 라이브 nav 동작·실패원인 규명 완료. 로봇 HOME 정상 복귀.**

---

## 1. 배경 / 목표

- 사용자가 새 맵 `mapv6.pgm` / `mapv6.yaml` 재생성 (mapv5_mocamap 대비 **좌표계 전면 변경**).
  - resolution 0.050→**0.030 m/px**, origin (-51.320,-6.624)→**(-8.327,-13.559)**, 643×458.
- 목표: 바뀐 맵 등록 → waypoint 찍기 → 라이브 Nav2 + AMCL 테스트.

---

## 2. 진단으로 밝혀진 SoT 구조 (Step 0)

- **`src/moca_navigation/` 가 실제 Nav2 SoT** (vicpinky_navigation 사본 + R2 patch, PinkLAB 원본은 frozen).
  `src/shared/vic_pinky/vicpinky_navigation/` 는 참고용(§0-B 보호).
- map 디폴트 경로 = `src/moca_navigation/map/` (사용자 지정). mapv6 는 PC·RPi 양쪽 이미 복사돼 있었음.
- **글로벌 플래너 최종 = SmacPlanner2D + MPPI(+PreferForwardCritic)** 로 확정.
  - run_nav2.sh 가 호출하던 `bringup_smachybrid_mppi_launch.xml` 는 **PC·RPi 어디에도 없는 죽은 launch** (이름만 잔재). 실제 params 는 NavFn+DWB 였음.
  - RPi `~/doby_controller/src/moca_navigation/` 에 다른 작업자가 만든 `bringup_smac_mppi.launch.xml` + `nav2_params_smac_mppi.yaml` 존재 → 이를 reference 로 PC 에 동일 복제.

---

## 3. 코드 변경 (전부 사용자 승인 후)

### moca_navigation (§0-B 외)
- **신규** `src/moca_navigation/launch/bringup_smac_mppi.launch.xml` — base bringup_launch.xml include + `nav2_params_smac_mppi.yaml` override. map default → `moca_navigation/map/mapv6.yaml`.
- **신규** `src/moca_navigation/params/nav2_params_smac_mppi.yaml` (RPi 본 복제). planner=SmacPlanner2D, controller=MPPIController, critics 8종(ConstraintCritic…PreferForwardCritic), 실측 비대칭 footprint `[[0.1,-0.27],[0.1,0.27],[-0.5,0.27],[-0.5,-0.27]]`.
  - **amcl `set_initial_pose: false` + initial_pose 블록 주석 처리** (기존 (-36.98,2.0) 은 mapv5 frame 라 무효 → RViz 2D Pose Estimate 수동 초기화 전제).
- `bringup_launch.xml` — map default `maps/mapv5.yaml` → `$(find-pkg-share moca_navigation)/map/mapv6.yaml`.
- `CMakeLists.txt` — install DIRECTORY 에 **`map` 추가** (기존 `launch params rviz` 만 → map/ 가 install 안 돼 find-pkg-share 경로에 mapv6 없던 문제 해결).

### §0-B 보호 스크립트 (사용자 명시 승인 1회)
- `scripts/run_nav2.sh`:
  - launch 호출 `vicpinky_navigation bringup_smachybrid_mppi_launch.xml`(죽은) → **`moca_navigation bringup_smac_mppi.launch.xml`**.
  - MAP_PATH `vicpinky_navigation` share → **`moca_navigation` share**. MAP 디폴트 `mapv5.yaml`→`mapv6.yaml`.
  - 헤더/echo "smac_hybrid+MPPI" → "SmacPlanner2D+MPPI" 정정.

### 신규 유틸
- `config/waypoints_mapv6_capture.yaml` — 캡처된 waypoint SoT.
- `scripts/capture_wp.py` — `map→base_footprint` TF 4회 읽어 안정성(spread) 체크 + yaml 추가/덮어쓰기. `# PYTHON_ARGCOMPLETE_OK` + argparse.
  - ⚠ 알려진 버그: 새 라벨 `--save` 시 파일 끝에 append → 마지막 섹션(home:) 으로 잘못 들어감. 기존 라벨 덮어쓰기는 제자리 OK. (W04 가 home 으로 들어가 수동 이동했음. 후속: `--section` 대로 삽입하도록 수정 필요.)

빌드: `colcon build --packages-select moca_navigation --symlink-install` → install 에 map/launch/params 반영 확인.

---

## 4. 캡처된 waypoint (mapv6 frame, map→base_footprint TF 기준, 4회 spread 0 확인)

`config/waypoints_mapv6_capture.yaml` — 최종 재기록본(2차):
```
W01 (6.936,-8.944, -1.590)   W02 (6.960,-10.674, 3.114)  W03 (6.358,-10.671, 3.118)
W04 (5.765,-10.678, 1.579)   W05 (5.733, -9.846, 1.591)  W06 (5.572, -6.740, 3.115)
W07 (-0.562,-6.854,-1.463)   W08 (-0.576,-10.677,-0.005) W09 (6.915,-10.606, 1.611)
W10 (7.346, -5.143,-0.006)   W11 (8.379, -6.804,-1.458)  W12 (8.327, -5.605,-1.563)
HOME (8.307, -5.619, -1.568)
```
- 캡처 방식 변천: 처음 `/amcl_pose echo`(정지 시 republish 안 떠 타임아웃) → **`map→base_footprint` TF rclpy lookup(재시도)** 로 안정화. (`ros2 topic echo` 파이프 버퍼링/`---` 멀티문서/따옴표 이스케이프 함정 다 겪음 → rclpy 직접 lookup 이 정답.)
- W04: 1차 캡처 때 정지(odom=0)인데 AMCL 2m+ 발산(불안정 구간)으로 보류 → 2차 재기록에서 채움.

---

## 5. 트러블슈팅 내역 (시간순)

| # | 증상 | 원인 | 해결 |
|---|---|---|---|
| 1 | run_nav2.sh 가 step2 에서 hang | RPi bringup 재기동 SSH 가 원격 백그라운드 launch 의 파이프 잡고 안 닫힘 | `timeout` 래핑 + kill·launch **별도 ssh 분리** |
| 2 | `pkill -f vicpinky_bringup` 가 ssh 세션 자살(exit 255) | 명령줄에 launch 문자열 포함 → pkill -f self-match | **bracket 패턴**(`vicpinky_brin[g]up`) + kill/launch 분리 |
| 3 | bringup "Failed to set velocity mode! Shutting down" | **e-stop 눌림** (모터 컨트롤러 velocity mode 거부) | e-stop 해제 후 재기동 |
| 4 | sllidar `SL_RESULT_OPERATION_TIMEOUT` 사망 | 옛 orphan sllidar(다른 패키지 경로라 kill 패턴 누락)가 `/dev/ttyUSB0` 점유 → 새 sllidar 포트 못 엶 | orphan 노드 **전부** bracket 패턴 kill → ttyUSB0 free 확인 후 단일 재기동 |
| 5 | AMCL "Failed to transform initial pose … extrapolation into the future" | 노트북↔RPi **시계 drift** (노트북 ntp.ubuntu.com, RPi 192.168.0.133 → 서로 다른 소스, 주행 중 TF 외삽 실패) | timesyncd drop-in `NTP=192.168.0.133` 으로 통일 → offset +116→-22ms 수렴 |
| 6 | /odom·/scan 끊김, AMCL cov 21.5 동결, 2D Pose Estimate 거부 | **collision_monitor heartbeat 4s 끊김 → lifecycle_manager_safety "CRITICAL FAILURE" → bringup 노드 일괄 종료** (odom 발행 노드 포함). nav2 1.3.7 RPi collision_monitor 취약점 | bringup 클린 재기동(orphan kill→relaunch) |
| 7 | 재기동 후 PC 에서 /scan_filtered "없음" | LaserScan = SENSOR_DATA(best_effort) QoS → 기본 RELIABLE echo 로 안 잡힘(표시 artifact). nav2 는 정상 수신. + daemon 재시작 필요 | `ros2 daemon stop/start` 재discovery + best_effort 로 확인 |
| 8 | NavigateToPose **허위 SUCCEEDED**(로봇 2.6m 밖인데 즉시 "Reached goal") | odom 재기동으로 (0,0) 리셋 직후 **map→odom TF 미확립** → goal 의 odom 변환이 로봇 근처로 잘못 매핑 | 재localize 로 map→odom TF 안정 확립(검증: tf lookup 3회 동일) |
| 9 | planner "Start occupied" (출발 거부) | 로봇이 **y≈-10.6 하단 벽줄** + cov 0.24(std 0.5m) + footprint + inflation → footprint 가 벽 cell 겹침. local costmap 10Hz 재마킹이라 클리어해도 즉시 재발 | 개활지로 이동 + cov 수렴 필요 |
| 10 | 벽줄 waypoint nav 반복 abort, 개활지(W08·8.33,-5.61)는 성공 | localization 정확도(cov) 부족 + 벽 근접 | 개활지로 6.8m 주행 → **cov 0.24→0.011 수렴** → 이후 안정 |

### 최종 회복 경로
시계 동기 → bringup 클린 재기동(/odom·/scan·모터 정상) → daemon 재discovery → 2D Pose Estimate(map→odom TF 안정 확인) → **개활지(8.33,-5.61) 로 nav → 6.8m 실주행 SUCCEEDED, cov 0.24→0.011 수렴 → HOME(8.28,-5.76, 목표 0.156m) 정상 도착.**

---

## 6. 핵심 발견 — 라이브 nav 신뢰성 조건

1. **odom 생존** — collision_monitor heartbeat 끊기면 safety manager 가 bringup(odom) 을 죽임. odom 죽으면 AMCL 동결 + 2D Pose Estimate 거부 + 모든 nav 실패. 증상: amcl_pose cov 폭발(>20) + map→odom TF stale.
2. **시계 동기** — 노트북·RPi 가 **동일 NTP master(192.168.0.133)** 여야. 정지 캡처는 견디지만 주행 중 연속 TF 조회에서 외삽 실패 유발. (SSH 왕복 drift 측정은 핸드셰이크 latency 로 inflated — 믿을 값은 `timedatectl` offset.)
3. **localization cov** — 초기 2D Pose Estimate 직후 cov ~0.24(std 0.5m) 는 느슨. **개활지 주행으로 0.01 수준 수렴** 후 벽줄 진입해야 "Start occupied" 회피.
4. **벽 근접 목표 전 costmap 클리어** + map→odom TF 안정 확인.

---

## 7. 미해결 / 다음 작업

- [ ] **capture_wp.py `--section` 삽입 버그** 수정 (현재 새 라벨이 파일 끝=home 섹션으로 들어감).
- [ ] **테이블 T01~T05 캡처** (Step 7, 미진행).
- [ ] **W04 위치 검증** — 1차 캡처 때 불안정 구간이었음. 2차 값(5.765,-10.678) RViz 재확인 권장.
- [ ] **collision_monitor heartbeat 취약점** — 주행 부하 시 재발 가능. nav2 1.3.7 RPi 버그(§CLAUDE.md). 재발 시 bringup 재기동 루틴 필요. 근본해결은 §0-B(vicpinky_bringup) 라 팀 협의.
- [ ] **NTP 영구화** — 노트북 timesyncd drop-in `/etc/systemd/timesyncd.conf.d/lan.conf` (NTP=192.168.0.133) 적용됨. "NTP 6대 통합" TODO 와 연계.
- [ ] **RPi `~/doby_controller` 동기** — PC SoT(mapv6 + smac_mppi launch/params + run_nav2.sh) 를 RPi clone 에도 반영(별 트랙, 사용자 routine).
- [ ] 벽줄 waypoint(W02~W04,W09~W11) nav 재검증 — cov 수렴 상태에서.

---

## 8. 변경 파일 목록

```
신규:
  src/moca_navigation/launch/bringup_smac_mppi.launch.xml
  src/moca_navigation/params/nav2_params_smac_mppi.yaml
  config/waypoints_mapv6_capture.yaml
  scripts/capture_wp.py
수정:
  src/moca_navigation/launch/bringup_launch.xml   (map default → mapv6)
  src/moca_navigation/CMakeLists.txt              (install 에 map 추가)
  scripts/run_nav2.sh                             (§0-B 승인 — moca_navigation smac_mppi launch + mapv6)
환경(로컬, repo 외):
  /etc/systemd/timesyncd.conf.d/lan.conf          (노트북 NTP=192.168.0.133)
```
