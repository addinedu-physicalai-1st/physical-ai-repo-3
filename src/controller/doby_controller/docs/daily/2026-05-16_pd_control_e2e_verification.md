# 2026-05-16 작업기록 — PD제어 업그레이드 + 3단계 E2E 검증

## 1. 요약

어제(2026-05-15)에 시작한 3단계 검증을 이어받아, approach_controller_node를 P제어에서 PD제어로
업그레이드하고 E2E 검증을 완료했다. 비상버튼 눌림 + collision_monitor scan 미수신 등 예상치 못한
하드웨어/소프트웨어 이슈를 진단하며 해결했다.

---

## 2. 주요 변경사항

### 2.1 approach_controller_node — P → PD 제어

**변경 이유**: 코너 추종 시 P제어만으로는 진동(oscillation)이 발생. D항이 변화율을 감지해 오버슈트 억제.

**PD 제어 수식**:
```
angular.z = -(Kp × err_x) - (Kd × d_err_x_filtered)
```

**EMA 필터 (지수이동평균)**:
```
d_filtered = alpha × raw_d + (1 - alpha) × prev_d_filtered
```
- `alpha=0.3` → 작을수록 강한 필터 (카메라 노이즈 억제)
- 이전값 70% 가중 → 급격한 미분값 변화 완화

**I항(적분) 제외 이유**:
- 카메라 추종에는 지속적 외력(마찰/바람)이 없어 지속오차 거의 없음
- 적분 와인드업(integral windup) — 타깃 소실 시 누적 오차 폭발 위험
- PD 만으로도 충분한 추종 성능 확인

**파라미터 (dev_common.launch.py)**:
```python
'angular_gain':    1.8,   # Kp (1.2→1.8, 코너 추종 반응 개선)
'derivative_gain': 0.3,   # Kd (신규)
'ema_alpha':       0.3,   # D항 EMA 필터 (신규)
'close_threshold': 0.55,  # bbox 높이 비율 기준 (cy → bh로 변경)
```

### 2.2 close_threshold: cy → bbox 높이 비율(bh)

**변경 이유**: cy(bbox 중심 y좌표)는 카메라 틸트/높이에 따라 기준이 달라져 불안정.
bbox 높이 비율(bh = bbox_height/frame_height)이 거리를 더 직접 반영.

- `/customer_pose.z` 에 bh 추가 (0~1, 클수록 가까움)
- `close_threshold=0.55` — bh가 0.55 이상이면 전진 정지 (근접 판단)

### 2.3 시각화 개선 (person_tracking_node)

- Persons/Groups 텍스트 → 왼쪽 하단 이동 (bbox 레이블에 가리는 문제 해결)
- 위치: `(10, h-40)`, `(10, h-10)`

---

## 3. 3단계 E2E 검증 결과

### 3.1 DBSCAN 멀티그룹 분리

- 2명 프린트 → G:0, 3명 프린트 → G:1 (또는 반대) 각각 분리 확인
- eps=450 (실물 사람용) vs eps=50 (프린트 테스트용) 차이 확인
  - 실물: 사람 bbox 중심 거리가 수백 픽셀 → eps=450 필요
  - 프린트: 종이 내부 인물들이 너무 가까워 eps=50으로만 분리 가능

### 3.2 인원수 최대 그룹 자동 선택

`group_approach_node.py:59`:
```python
target = max(candidates, key=candidates.__getitem__)
```
→ 이미 구현돼 있었음. 별도 수정 불필요.

**흐름**:
```
DBSCAN 그룹핑
    → group_approach_node: 인원수 최대 그룹 선택
    → person_tracking_node: 타깃 그룹 내 bbox 면적 최대(=가장 가까운) 사람 pose
    → approach_controller: PD제어로 해당 pose로 이동
```

**파라미터 주의**:
- `min_group_size: 1` (현재 dev_common) → 1인도 대상 포함 (테스트용)
- 실제 운영 시 `min_group_size: 2`로 → 2인 이상 군중만 호객 대상

### 3.3 로봇 물리 추종 확인

- 프린트를 카메라 앞에 갖다 대자 approach_target=0, linear.x=0.15 발행 확인
- 로봇이 프린트 방향으로 실제 추종 동작 확인

---

## 4. 진단한 하드웨어/소프트웨어 이슈

### 4.1 비상버튼 눌림 → ZLAC 연결 실패

**증상**: bringup 재시작 시 "Failed to set velocity mode! Shutting down." 반복
**원인**: 비상버튼(e-stop)이 눌린 상태에서 ZLAC 모터 컨트롤러가 명령 거부
**해결**: 비상버튼 해제 → bringup 재시작 → 정상

**교훈**: 강제 종료(kill) 후 재시작 시 항상 비상버튼 상태 먼저 확인.

### 4.2 collision_monitor TF 오래된 데이터 문제

**증상**: bringup 2.5시간 경과 후 collision_monitor가 /cmd_vel 미발행
**원인**:
- laser_filters(/scan_filtered) 노드 오동작 → scan source timeout
- 오래된 TF(laser_link→base_link) — 2.5시간 전 발행, 현재 시각 기준 extrapolation 실패
**임시 해결**: `transform_tolerance: 10000.0`, `topic: "/scan"` 로 변경 후 테스트
**원복**: 테스트 후 원래값 복구 (`transform_tolerance: 0.5`, `topic: "/scan_filtered"`)

**근본 원인 미해결**: laser_filters가 왜 중단되는지 미확인. 후속 과제.

### 4.3 노드 중복 실행

**증상**: dev_common 재시작 누적 → person_tracking_node 3개 동시 실행 → 토픽 충돌
**해결**: `pkill -f person_tracking_node` 후 단일 인스턴스 재시작

---

## 5. 오늘 확인한 검증 체크리스트

| 항목 | 상태 |
|---|---|
| YOLOv8 + BoT-SORT 실시간 추적 | ✅ |
| DBSCAN 멀티그룹 분리 | ✅ (프린트로 검증) |
| 인원수 최대 그룹 자동 선택 | ✅ (코드 확인) |
| PD제어 angular.z 발행 | ✅ |
| bbox 높이 기반 close_threshold | ✅ (코드 변경) |
| 로봇 물리 추종 | ✅ (프린트 따라옴) |
| 실물 사람 close_threshold 거리 검증 | 🔜 월요일 계속 |
| 실물 2인 이상 멀티그룹 우선 접근 | 🔜 팀원 합류 후 |

---

## 6. 추가 진단 — 2026-05-16 오후 (실물 사람 검증 시도)

### 6.1 collision_monitor SIGABRT (nav2 1.3.7 RPi 버그)

**증상**: bringup 재시작 후 collision_monitor가 exit code -6 (SIGABRT)로 crash
**임시 조치**: bringup.launch.xml에서 collision_monitor 노드 주석 처리
- velocity_smoother output remapping: `smoothed_cmd_vel → cmd_vel` (잘못된 이름)
- **미해결**: 실제 내부 토픽 이름은 `cmd_vel_smoothed`임을 나중에 발견

### 6.2 QoS 불일치 — 가장 큰 발견

**증상**: approach_controller_node가 /bt/cmd_vel을 발행하는데 twist_mux가 못 받음
**원인**:
```
approach_controller_node (publisher): Reliability = RELIABLE
twist_mux (subscriber):               Reliability = BEST_EFFORT
```
RELIABLE publisher ↔ BEST_EFFORT subscriber → DDS QoS 불일치 → 데이터 미전달
**수정**: approach_controller_node publisher를 BEST_EFFORT로 변경 (커밋 98a2ba0)

### 6.3 velocity_smoother remapping 오류

**증상**: bringup.launch.xml에서 `smoothed_cmd_vel:=cmd_vel` remapping했으나 미적용
**원인**: nav2_velocity_smoother의 실제 내부 출력 토픽 이름은 `cmd_vel_smoothed`
- 올바른 remapping: `<remap from="cmd_vel_smoothed" to="cmd_vel"/>`
**상태**: 월요일에 수정 필요

### 6.4 bh(bbox 높이 비율) 항상 0.99+

**증상**: 실물 사람이 카메라 앞에 서면 bh가 항상 0.99 이상 → close_threshold=0.55,0.85 모두 항상 전진 정지
**원인**: 카메라 화각 대비 사람 크기 → 거리에 상관없이 bbox가 화면을 가득 채움
**임시 대응**: close_threshold 0.55 → 0.85로 변경
**상태**: 월요일에 실제 거리별 bh 값 측정 후 적절한 값 결정 필요

---

## 7. 다음 단계 (월요일)

### 7.1 즉시 수정 필요
1. **bringup.launch.xml velocity_smoother remapping 수정**:
   - `smoothed_cmd_vel` → `cmd_vel_smoothed` (올바른 내부 이름)
   - RPi scp 재전송 후 bringup 재시작

2. **collision_monitor 복구 또는 영구 우회**:
   - nav2 1.3.10 업그레이드 시도 또는
   - velocity_smoother → /cmd_vel 직통 구조로 운영

### 7.2 검증 재시도
1. 로봇 물리 이동 확인 (angular.z + linear.x 모두 전달되는지)
2. 실물 사람 거리별 bh 측정 (1m, 1.5m, 2m에서 bh 값 기록)
3. 적절한 close_threshold 결정 후 정지 거리 검증
4. 실물 2인 이상 멀티그룹 우선 접근 (min_group_size: 2)
