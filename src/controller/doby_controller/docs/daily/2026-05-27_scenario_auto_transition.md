# 2026-05-27 (저녁) — 시나리오 자동 전환 연동

> 세션 목표: 그룹탐지→접근→게임→감정→추종 전체 흐름을 수동 개입 없이 자동으로 이어지도록 연동

---

## 1. 완성된 전체 시나리오 흐름

```
[항상 실행]
  person_tracking (YOLO + BoT-SORT + DBSCAN)
  GEVA (웹캠 → 감정 valence/arousal)
  mode_manager (모드 FSM)

[시나리오 자동 흐름]
  사람 탐지/그룹 감지
    ↓ (group_approach_node → approach_controller)
  로봇 그룹 접근 (PD제어, /bt/cmd_vel)
    ↓ (bh >= close_threshold)
  ★ approach_controller → SetMode('engaging') 자동 호출
    ↓
  engaging 모드: 게임/아이스브레이크 + GEVA 감정분석 실행
    ↓ (valence >= 0.3)
  ★ target_selector → customer_id 확정 → SetMode('follow') 자동 호출
    ↓
  follow 모드: 1인 추종 (follow_controller)
```

---

## 2. 수정된 파일

### 2.1 `approach_controller_node.py` (RPi mobility_controller)

close_threshold 도달 시 SetMode('engaging') 자동 호출 추가:

```python
# 추가된 import
from dobi_npc_msgs.srv import SetMode

# __init__ 에 추가
self._engaging_triggered: bool = False
self._set_mode_client = self.create_client(SetMode, '/mode/request')

# _tick() — close_threshold 도달 시
elif not self._engaging_triggered:
    self._engaging_triggered = True
    self._switch_to_engaging()

# 새 메서드
def _switch_to_engaging(self):
    req = SetMode.Request()
    req.requested_mode = 'engaging'
    req.params = '{}'
    self._set_mode_client.call_async(req)
```

### 2.2 `target_selector_node.py` (dobi_npc_bringup)

valence >= threshold 시 SetMode('follow') 자동 호출 추가 (이전 세션에서 완료):

```python
# customer_id 확정 후 한 번만 follow 모드 전환
if not self._mode_switched:
    self._mode_switched = True
    self._switch_to_follow()
```

### 2.3 `mode_engaging.launch.py`

customer_identity_node + target_selector_node 추가:
- engaging 모드 중 track_id → customer_id 매핑 실행
- engaging 모드 중 GEVA 감정 분석 결과를 지켜보다가 follow 자동 전환

### 2.4 `run_follower.sh`

- mode_follow.launch.py → mode_engaging.launch.py 로 변경
- SetMode 'follow' → SetMode 'engaging' 로 변경
- 이후 전환은 target_selector 자동 처리 (설명 주석 추가)

---

## 3. 의존성 추가 — approach_controller_node.py

RPi 에서 `dobi_npc_msgs` 패키지가 필요:
- 이미 `~/doby_controller/install/` 에 빌드되어 있으면 OK
- SetMode.srv 인터페이스 사용

---

## 4. 내일 확인 사항 (빅핑키 필요)

1. **approach_controller → engaging 전환**: close_threshold 도달 시 로그 확인
   ```
   [approach_controller] → engaging 모드 자동 전환 요청 (close_threshold 도달)
   ```

2. **target_selector → follow 전환**: 감정 분석 후 로그 확인
   ```
   [target_selector] 추종 대상 선택: customer_id=... (valence=...)
   [target_selector] → follow 모드 자동 전환 요청
   ```

3. **전체 흐름**: `bash run_follower.sh` 한 번으로 전체 시나리오 동작

---

*관련: `docs/daily/2026-05-27_botsort_thresh_fix.md` (오전/오후 세션)*
*다음 세션: 빅핑키 탑재 → 전체 시나리오 연동 테스트 → 데모 촬영*
