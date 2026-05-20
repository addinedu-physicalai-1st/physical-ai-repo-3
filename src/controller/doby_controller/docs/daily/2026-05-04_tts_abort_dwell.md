# tts_node abort dwell — face_avatar dwell 패턴 대칭화

**작성일**: 2026-05-04 (SafetyCheck /scan 직후)
**작업자**: 공국진 (Stephen)
**프로젝트**: Dobi Barista 호객 BT 시스템
**대응 TODO**: CLAUDE.md §10 "음성/표정 dwell 통합: tts_node에 abort dwell (현재 face만)"
**상태**: tts_node에 `abort_dwell_sec` (기본 2.0s) 추가. abort 후 일정 시간 지연 도착 utter 무시. 라이브 검증 통과.

---

## 0. 시작 컨텍스트

기존 dwell 비대칭:
- **face_avatar**: abort 후 `abort_dwell_sec` (2.0s) 동안 새 expression 무시 → BT halt 직후 race로 도착하는 expression publish 차단
- **tts_node**: abort 즉시 mixer.stop() 만, dwell 없음 → 같은 race 윈도우에 들어온 utter는 그대로 재생됨

→ 음성과 표정 일관성 깨짐. abort 후 1초 안에 stale utter가 도착하면 robot 입은 다른 말 하고 face는 basic 유지.

---

## 1. 구현 — `tts_node.py` (~15줄)

face_avatar 의 dwell 패턴을 대칭으로 옮김. 같은 파라미터명, 같은 기본값(2.0s).

### 1.1 파라미터

```python
self.declare_parameter('abort_dwell_sec', 2.0)
```

— 0이면 비활성. 매 abort_trigger 수신 시 timer reset (sustained abort 동안 연장).

### 1.2 상태

```python
self._dwell_until = 0.0   # monotonic time. 이 시각 이전엔 utter 무시
```

— face_avatar는 `pygame.time.get_ticks()` 사용(pygame.init 의존). tts_node는 mixer.init만 하므로 표준 `time.monotonic()` 사용.

### 1.3 abort_trigger 시 timer 갱신

```python
def _on_rapport(self, msg: RapportEvent):
    if msg.event_type != "abort_trigger":
        return
    if self.abort_dwell_sec > 0:
        self._dwell_until = time.monotonic() + self.abort_dwell_sec
    # ... 기존 mixer.stop() 로직
```

— abort_trigger 메시지 도착할 때마다 reset. rapport_tracker가 sustained abort 중 매 100ms 발행하므로 dwell이 자연스럽게 연장됨.

### 1.4 utter 시 dwell 체크

```python
def _on_utter(self, msg: UtterRequest):
    text = (msg.text or '').strip()
    if not text:
        return
    now = time.monotonic()
    if now < self._dwell_until:
        remaining = self._dwell_until - now
        self.get_logger().info(
            f"abort dwell {remaining:.1f}s remaining → ignore "
            f"[{msg.persona_id}/{msg.stage_id}] {text!r}")
        return
    # ... 기존 합성/재생
```

— face_avatar는 abort_expression 자체는 통과시켰는데, tts_node는 발화 텍스트가 abort 상황에 적합한지 알 길이 없으므로 모든 utter 차단. abort 후엔 어차피 BT halt 상태라 정상 흐름에선 utter 안 옴 — dwell은 race 케이스 안전망.

---

## 2. 라이브 검증

```bash
ros2 run dobi_npc_dialog tts_node &
sleep 3
ros2 topic pub --once /rapport/event dobi_npc_msgs/msg/RapportEvent \
  "{event_type: abort_trigger, reason: test_abort}"
sleep 0.3
ros2 topic pub --once /dialog/utter dobi_npc_msgs/msg/UtterRequest \
  "{text: 안녕, voice: ko-KR-SunHiNeural}"           # 차단 기대
sleep 2.0
ros2 topic pub --once /dialog/utter dobi_npc_msgs/msg/UtterRequest \
  "{text: 통과, voice: ko-KR-SunHiNeural}"           # 통과 기대
```

```
[INFO] tts_node ready: ... abort_dwell=2.0s
[INFO] abort dwell 0.4s remaining → ignore [test_p/test_s] '안녕'
[INFO] speak [test_p/test_s3/ko-KR-SunHiNeural/+0%/+0Hz/face=-] '통과'
[INFO] utter_done
```

— ✅ dwell 중인 utter는 ignore 로그 + skip. 만료 후 utter는 정상 재생 + utter_done.

(`ros2 topic pub --once`의 discovery 지연으로 abort 수신 시점이 sleep 명령보다 ~1.6s 늦어 "0.4s remaining"으로 잡혔지만 동작은 정확.)

---

## 3. 발견 / 함정

### 3.1 abort_trigger 도착이 silent해도 dwell은 갱신됨

`_on_rapport`의 WARN 로그 ("abort_trigger → mixer.stop()") 는 **mixer가 busy일 때만** 발화. mixer idle 상태에서 abort 도착하면 로그 없이 dwell만 연장됨. face_avatar도 face state 변화 시에만 로그 — 같은 패턴.

운영자가 "왜 utter가 무시되지?" 디버깅할 때, dwell ignore 로그(`abort dwell N.Ns remaining → ignore`)가 단서가 됨.

### 3.2 monotonic vs ROS clock

`time.monotonic()` 사용 — 시스템 시계 변경에 영향 안 받고, ROS sim time 무관(TTS는 wall-clock 발화 박자).

face_avatar의 `pygame.time.get_ticks()`는 pygame 초기화 후 첫 tick부터의 ms. tts_node는 pygame.init() 안 하고 mixer만 init하므로 `pygame.time.get_ticks()` 사용 시 0 반환. 표준 라이브러리로 통일.

### 3.3 abort_expression 동등 개념 없음

face_avatar는 `abort_expression="basic"`을 설정해 dwell 중에도 abort_expression 자체는 통과시킴(sustained abort 중 BT가 우연히 같은 expression 재요청 케이스 흡수). tts_node는 발화 텍스트의 의미(abort 상황 적합 여부)를 판단할 길 없음 → **모든 utter 차단**으로 단순화. 정상 BT halt 흐름에선 dwell 윈도우에 utter가 안 들어옴.

### 3.4 dev launch 파라미터 미설정 → 기본 2.0s

`launch/dev_*.launch.py`에 `abort_dwell_sec` 명시 안 함. 기본값 2.0이 face_avatar와 일치하므로 추가 작업 없음. 페르소나별 dwell 변경이 필요하면 후속 (TODO §"persona별 dwell/abort_expression").

---

## 4. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/dobi_npc/dobi_npc_dialog/dobi_npc_dialog/tts_node.py` | `abort_dwell_sec` 파라미터 + `_dwell_until` 상태 + `_on_utter` dwell 체크 + `_on_rapport` timer 갱신 + ready 로그 (~15줄) |

---

## 5. 다음 / TODO 갱신

### CLAUDE.md TODO 변경
- `[ ] 음성/표정 dwell 통합: tts_node에 abort dwell` → **`[x] 음성/표정 dwell 통합 (2026-05-04, abort_dwell_sec=2.0 기본, face_avatar와 대칭)`**

### 후속 (관련성)
- [ ] **persona별 dwell**: 페르소나 YAML에 `abort_dwell_sec` 필드 추가, persona_manager가 ROS 파라미터 set으로 노드 갱신 — 글로벌 → 페르소나 단위 세밀화
- [ ] **dwell 누적 로깅**: 라이브에서 dwell ignore 빈도 측정 (race가 실제로 얼마나 자주 발생하는지)

---

## 6. 한 줄 요약

> tts_node에 `abort_dwell_sec=2.0` 추가. abort 후 race로 지연 도착하는 utter 차단. face_avatar dwell과 대칭, time.monotonic() 기반, 라이브 검증 통과.
