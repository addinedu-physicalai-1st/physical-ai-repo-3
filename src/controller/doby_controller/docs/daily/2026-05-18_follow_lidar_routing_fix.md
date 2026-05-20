# 2026-05-18 작업기록 — follow 모드 LiDAR 거리 제어 + twist_mux 라우팅 수정 + 3단계 E2E 검증

## 1. 요약

follow 모드 3단계 E2E 검증 완료.
HCAM01N bbox 높이로 거리 판별 불가 문제를 LiDAR 기반 제어로 전환하고,
twist_mux 라우팅 차단 문제를 해결해 추종 + 30cm 정지 동작을 실물 확인했다.

---

## 2. 핵심 수정 내용

### 2-1. follow_controller_node.py — NameError 수정

```python
# 수정 전 (NameError)
cx, _cy, _w, _h = self._target_bbox
...
self._maybe_log(v, w, err_angle, err_dist, h)   # h가 없음

# 수정 후
self._maybe_log(v, w, err_angle, err_dist, _h)
```

### 2-2. LiDAR 기반 거리 제어 (bbox 높이 → scan_front)

**배경**: HCAM01N 광각 카메라는 1m~2m 범위에서 bbox 높이가 0.997~0.999로 고정 → 거리 판별 불가.

```python
# 수정 전 (bbox 높이 기반, 무효)
err_dist_raw = self.target_h_ratio - (h / self.image_h)

# 수정 후 (LiDAR 기반)
if self._scan_received and math.isfinite(self._scan_front_min):
    err_dist_raw = self._scan_front_min - self.target_dist
else:
    err_dist_raw = 0.0
```

`err_dist = scan_front_min - target_dist`:
- 양수 = 사람이 target_dist보다 멀다 → 전진 (v > 0)
- 음수 = 사람이 target_dist보다 가깝다 → 후진 (v < 0)
- kp_linear 양수 부호로 변경 (0.8)

### 2-3. twist_mux 라우팅 차단 문제 해결

**원인**: twist_mux 우선순위 구조
- `/joy/cmd_vel` (priority 100): teleop_server → mode='idle'일 때 20Hz 발행
- `/bt/cmd_vel` (priority 80): approach_controller → 타겟 없어도 0,0 20Hz 발행
- `/follow/cmd_vel` (priority 50): follow_controller → 차단됨

**해결**:

1. **teleop_server**: mode='follow'에서 자동 발행 중단 (기존 로직, 정상 동작)
2. **approach_controller_node.py**: 타겟 없을 때 publish 제거
   ```python
   # 수정 전
   self._pub.publish(twist)  # 타겟 없어도 0,0 발행
   return
   
   # 수정 후
   return  # 발행 안 함 → 0.5s 후 twist_mux 타임아웃 → /bt/cmd_vel 비활성
   ```
3. **mode_manager_node.py**: battery NaN → -1.0 처리
   ```python
   self._battery_pct = pct if math.isfinite(pct) else -1.0
   ```
   NaN < 0.0이 False라 기존 코드가 battery_low로 잘못 판단 → follow 모드 진입 차단됨.

### 2-4. dev_common.launch.py — close_threshold 수정

```python
'close_threshold': 0.999,  # 0.85 → 0.999 (HCAM01N bbox 높이 항상 0.997~0.999)
```

---

## 3. 라이브 튜닝 결과 (mode_follow.launch.py 확정값)

| 파라미터 | 이전 | 확정 | 이유 |
|---|---|---|---|
| `target_dist` | 0.7m | 0.30m | 실측 기반 사용자 결정 |
| `kp_angular` | 1.2 | 0.5 | 흔들림 감소 |
| `align_gate` | 0.10 | 0.0 | 회전+전진 동시 → 추종 응답성 ↑ |
| `angle_smoothing_alpha` | 0.2 | 0.4 | EMA 빠른 수렴 (감지 불안정 대응) |
| `angle_deadband` | 0.10 | 0.15 | 소각도 노이즈 무시 |
| `dist_deadband` | 0.05 | 0.02 | EMA 리셋 후 빠른 수렴 |
| `kp_linear` | -0.8 (부호 오류) | 0.8 | LiDAR 기반 양수 |
| `scan_stop_dist` | 0.45 | 0.30 | vicpinky 섀시 0.25 + 마진 |

---

## 4. 발견된 구조적 문제들

### 4-1. twist_mux 우선순위 설계 미스매치

follow 모드 전용 채널(priority 50)이 항상 켜져있는 approach_controller(priority 80)에 차단됨.
approach_controller가 타겟 없어도 0 명령을 계속 발행하는 것이 원인.

**해결**: approach_controller 타겟 없을 때 publish 제거. twist_mux 0.5s 타임아웃으로 자동 비활성.

### 4-2. usb_cam 간헐적 종료

mode_follow 재시작 과정에서 usb_cam(RPi)이 죽는 경우 발생.
수동으로 SSH → `ros2 run usb_cam usb_cam_node_exe` 재시작으로 복구.

**근본 원인 미파악** — 향후 watchdog 추가 필요.

### 4-3. mode_manager zombie 프로세스

SetMode('follow') 반복 호출 시 이전 follow stack을 kill하지 않고 새 stack을 spawn.
수동으로 `pkill`로 정리 필요.

---

## 5. 3단계 E2E 검증 결과

| 항목 | 결과 |
|---|---|
| 사람 감지 (person_detector) | ✅ 50~56% 검출율 (HCAM01N 광각 환경) |
| 각도 추종 (kp_angular=0.5) | ✅ 좌우 회전으로 사람 방향 유지 |
| 거리 제어 (LiDAR, target=0.30m) | ✅ 30cm에서 정지 확인 |
| 전체 파이프라인 | ✅ follow_controller → /follow/cmd_vel → twist_mux → /cmd_vel_raw → velocity_smoother → /cmd_vel → 모터 |
| 흔들림 | ⚠️ 경미한 좌우 흔들림 존재 (파라미터 튜닝 범위 — 구현 단계로 이월) |

---

## 6. 다음 단계

검증 완료. 구현 단계 진입.

- [ ] approach_controller zombie 방지 (mode_manager kill 로직 보완)
- [ ] usb_cam watchdog (run_teleop_ui.sh에 pgrep 루프 추가)
- [ ] 흔들림 추가 튜닝 (kp_angular, angle_deadband)
- [ ] GEFA 기반 자세 추정 통합 (Phase 2 후속)
