# follow target_height_ratio 라이브 캘리브 — 노트북 게임 거리(~50cm)

**작성일**: 2026-05-04 (follow 모드 실 구현 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md follow 후속 "target_height_ratio=0.5 라이브 캘리브"
**상태**: `scripts/calibrate_follow.py` 신규 + 라이브 캘리브로 `target_height_ratio=0.97` 확정.

---

## 0. 시작 컨텍스트

전 단계에서 follow_controller 기본값 `target_height_ratio=0.5` (= bbox 높이가 frame 50%, 약 2m 정거리). 그러나 본 시스템의 의도는 **손님이 노트북 풀스크린 게임 화면을 보면서 RPS 미니게임을 플레이**할 수 있어야 함 — 따라서 follow 거리는 게임 가시성 기준으로 정해져야지 일반 추종 거리가 아님.

라이브 측정으로 사용자 의도 거리에서 bbox_h_ratio가 어떻게 나오는지 확인 필요.

---

## 1. 캘리브 도구 — `scripts/calibrate_follow.py`

`/robot_cam/persons` (vision_msgs/Detection2DArray) 구독 → 가장 큰 bbox의 `size_y / image_h` 롤링 통계 출력. follow_controller 미띄움 → cmd_vel 발행 0 (안전).

### 1.1 흐름

```
사전: bash scripts/run_robot_cam.sh + ros2 run dobi_npc_emotion person_detector
실행: python3 scripts/calibrate_follow.py [--image-height 480] [--window 5]
```

매 1초:
```
window=5s N=20 mean=0.997 std=0.004 min=0.988 max=1.000 |hint≈<0.7m (매우 가까움)
```

Ctrl-C 시:
- 마지막 5초 윈도우(권장 — 안정 시점)
- 전체 누적 (fallback — Ctrl-C 시 사람이 frame 안 들어와있을 때 대비)
- 거리 hint + 적용 코드 snippet

### 1.2 거리 hint 매핑 (rough)

| ratio | hint |
|---|---|
| ≥ 0.85 | <0.7m (매우 가까움) |
| 0.6~0.85 | 0.7~1.2m |
| 0.4~0.6 | 1.2~2m |
| 0.25~0.4 | 2~3m |
| 0.15~0.25 | 3~5m |
| < 0.15 | >5m (원거리) |

calibrated 아님 — 카메라 마운트/HFOV/사람 자세에 따라 변동. 보조 지표.

---

## 2. 라이브 캘리브 결과

```
person 검출 frames   : 364 (전체 1449 frames의 25%)
[전체 누적]          : N=364 mean=0.969 std=0.125 range=0.346~1.000
거리 hint            : <0.7m (매우 가까움)

권장 target_height_ratio: 0.97
```

range가 넓은 이유: 캘리브 중 사용자가 자세 변경 + 짧게 멀어졌다 가까워지기 반복. 주된 자세는 카메라 정면에서 ~50cm 거리, ratio 0.95~1.00. 이상적 follow 위치 = 손님이 노트북 풀스크린 게임 화면 보고 게임할 때 자연스러운 거리.

---

## 3. 적용 — `mode_follow.launch.py`

```python
parameters=[{
    'target_height_ratio': 0.97,    # 캘리브: 손님 게임 거리 ~50cm
    'params_json': ...,
}]
```

기본값 0.5 → 0.97 override. 캘리브 결과 + 의도(게임 가시성) 코멘트 포함.

---

## 4. 발견 / 함정

### 4.1 가까운 follow와 scan_stop_dist=0.8m 의 충돌

target_height_ratio=0.97 → robot은 손님이 ~50cm 거리에 있을 때 만족 (err_dist=0). scan_stop_dist=0.8m는 obstacle 가까울 때 forward 차단. 즉 **로봇이 cmd_vel로 50cm까지 능동적으로 다가가지는 못함** — 손님이 스스로 가까이 올 때만 50cm에 도달.

게임 시나리오에 부합:
1. 로봇이 손님을 발견 → follow 모드 진입
2. err_dist 양수 (손님이 멀리 있음) → forward (scan 클리어)
3. scan이 0.8m 도달 → forward 차단, 회전만 (각도 추적)
4. 손님이 게임하려고 가까이 옴 → ratio 1.0 근접 → err_dist≈0 → 정지
5. 게임 진행

문제 없음. scan_stop_dist를 0.4~0.5m로 낮추면 로봇이 적극 다가가지만 안전 마진 ↓. 현 정책 유지.

### 4.2 std=0.125로 넓은 분포

전체 누적 std는 사용자가 캘리브 중 위치 변경 / 일시 frame 이탈 등 포함. 안정 위치만 잡으려면 마지막 5초 윈도우 권장. 본 케이스는 짧은 윈도우(N=0) → 누적 사용. 후속 캘리브 시 **마지막 5초 동안 움직이지 말고 Ctrl-C** 권장.

### 4.3 range 0.346~1.000 의 의미

최댓값 1.000은 frame 가득 참 (사람이 매우 가까이 옴). 최솟값 0.346은 일시 멀어졌을 때(2~3m hint). 자연스러운 range. mean 0.969가 사용자가 "여기"라고 정한 거리 근사.

### 4.4 카메라 HFOV / 마운트 캘리브 미수행

본 라이브 캘리브는 **bbox_h_ratio 자체**의 라이브값 측정만. 정확한 거리(m 단위)와의 관계는 카메라 intrinsic 캘리브(focal length 측정) 후 `d = f * H_real / h_pixel`로 변환 가능. 본 작업은 P 제어의 setpoint 라이브 매칭만 — 실 거리(m)는 LiDAR scan과 비교해 필요 시 후속.

---

## 5. 변경 파일

| 파일 | 변경 |
|---|---|
| `scripts/calibrate_follow.py` | 신규 (~140 줄) — bbox_h_ratio 라이브 통계 + 추천값 print |
| `src/dobi_npc/dobi_npc_bringup/launch/mode_follow.launch.py` | follow_controller `target_height_ratio: 0.97` override |

---

## 6. 다음 / TODO 갱신

### CLAUDE.md TODO
- `[ ] target_height_ratio 캘리브` → **`[x] target=0.97 (2026-05-04, 게임 가시성 ~50cm)`**

### 후속 (관련성)
- [ ] **카메라 intrinsic 캘리브**: focal length 측정 → bbox_h → 실 거리(m) 변환. opencv chessboard 캘리브 또는 알려진 거리 객체로 1회 측정.
- [ ] **scan_stop_dist 페르소나별**: 게임 모드(close) vs 일반 follow(safety) 구분 시 페르소나/모드 인자.
- [ ] **bbox_h vs LiDAR 보정**: bbox_h가 사람 자세에 민감 (앉으면 ratio↓). LiDAR 거리와 fusion 시 robust.

---

## 7. 한 줄 요약

> `scripts/calibrate_follow.py` 신규 + 라이브 캘리브로 `target_height_ratio=0.97` 확정. 의도는 손님이 노트북 풀스크린 게임 화면을 보면서 RPS 플레이할 거리(~50cm). 364 샘플 검증, mode_follow.launch.py 적용.
