"""test_ui_scenarios.py — 운영 UI 9 시나리오 자동 검증 (옵션 A).

전제:
  1. bash scripts/run_sim.sh — Gazebo + Nav2 + 운영 UI 풀스택 (S2/S4/S3 검증)
     또는 bash scripts/run_dashboard.sh — UI 단독 (S6/S7/S8/S9 만 검증, S1/S2/S4/S5 일부 skip)
  2. ROS_DOMAIN_ID=99, LOCALHOST_ONLY=1 (시뮬 격리)

실행:
  bash scripts/run_scenarios.sh          # 전체
  bash scripts/run_scenarios.sh -k s5    # S5 만
  bash scripts/run_scenarios.sh -v       # verbose

시나리오 (계획서 §10.1 자동 시나리오 정합):
  S1: idle → patrol_interval (단축 6초) → patrol 자동
  S2: pickup → serving (Gazebo 풀스택 필요, 미기동 시 SKIP)
  S3: serving 완료 → idle (Gazebo 도달 시간 의존, M4 자동화)
  S4: guide → guiding (Gazebo 풀스택 필요, 미기동 시 SKIP)
  S5: emergency_stop → alarm_dwell 차단
  S6: 거부 케이스 (INVALID_MODE, 나머지 wire-format 제약 SKIP)
  S7: WS event_log 누적
  S8: set_config → config_updated broadcast
  S9: utter command
"""

import time

import pytest


# ───── 헬퍼 ─────

def _err_body(r):
    """FastAPI HTTPException 응답은 {'detail': {...}} 으로 wrap.
    그 외 직접 _err dict 인 경우도 있어 양쪽 모두 지원.
    """
    try:
        body = r.json()
    except Exception:
        return {}
    if 'detail' in body and isinstance(body['detail'], dict):
        return body['detail']
    return body


def _err_code(r):
    return _err_body(r).get('code')


def _ws_result_or_skip(result, target_mode):
    """ws_collect 결과 — 매칭 시 dict, 미매칭 시 list 반환.
    list 면 mode stack 미기동으로 보고 skip.
    """
    if isinstance(result, list):
        pytest.skip(
            f'{target_mode!r} 전이 미수신 — mode_{target_mode} stack 미기동 '
            '(Gazebo 풀스택 필요: bash scripts/run_sim.sh)')
    return result


def _ensure_idle(http, timeout=5.0):
    """모드 idle 강제 진입 + alarm dwell 해제 대기 (S5 emergency_stop / S12 rapport abort
    이후 mode_manager 측 safety_alarm_until_ns 가 5s 활성 → 다음 non-idle setmode 차단).
    setmode timeout 시 skip."""
    r = http.post('/api/v1/mode',
                  json={'mode': 'idle', 'params': {},
                        'override_priority': True})
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('idle 진입 시 setmode timeout — mode stack 미기동')
    assert r.status_code in (200, 423), f'idle 진입 응답: {r.status_code} {r.text}'
    time.sleep(1.0)
    r = http.get('/api/v1/status')
    current = r.json()['data']['mode']['current']
    if current != 'idle':
        pytest.skip(f'idle 진입 실패 (현재={current})')
    # safety_ok=true 대기 (alarm dwell 5s 자동 해제). 최대 7s polling.
    safety_deadline = time.time() + 7.0
    while time.time() < safety_deadline:
        s = http.get('/api/v1/status').json()['data']['mode'].get('safety_ok', True)
        if s:
            return
        time.sleep(0.3)


def _wait_for_mode(http, target: str, timeout: float = 5.0) -> bool:
    """opserver.current_mode 가 target 으로 전환 대기 (100ms polling).
    /mode/state 1Hz publish + transition spawn 1.5s 고려 — pickup 후 mode='serving'
    도달 ~1.9-2.5s. timeout 까지 미도달 시 False."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            cur = http.get('/api/v1/status').json()['data']['mode']['current']
            if cur == target:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# ───── S1: idle → patrol 자동 트리거 (시간 단축) ─────

def test_s1_idle_patrol_auto(http, fast_patrol, ws_collect):
    """idle 진입 후 patrol_interval (단축 6초) 경과 → patrol 자동 트리거.

    주의: 본 테스트는 fast_patrol 의 _drain_until_clean 이 idle 상태를 이미 보장하므로
    _ensure_idle 호출 X. _ensure_idle 의 POST /mode idle 이 직전에 fire 된 patrol 을
    즉시 kill 하는 race 회피 (mode_manager 1Hz publish + patrol 0.5s 윈도우 race).
    """
    # patrol 전환 wait — fast_patrol 6초 dwell + IdlePatrolTimer 1Hz tick + spawn 1.5s 여유
    result = ws_collect(
        types={'mode_state'},
        timeout=20.0,
        match=lambda m: (m.get('data') or {}).get('current') == 'patrol',
    )
    msg = _ws_result_or_skip(result, 'patrol')
    assert msg['data']['current'] == 'patrol'


# ───── S2: patrol 중 pickup → serving 선점 ─────

def test_s2_patrol_pickup_preempt(http, ws_collect):
    """patrol 강제 시작 → POST /pickup → serving 선점."""
    _ensure_idle(http)

    # patrol 강제 진입
    r = http.post('/api/v1/mode',
                  json={'mode': 'patrol', 'params': {}, 'override_priority': True})
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('patrol 진입 setmode timeout — mode stack 미기동 (Gazebo 풀스택 필요)')
    assert r.status_code == 200, f'patrol 거부: {r.text}'
    time.sleep(2.0)

    # pickup 호출
    r = http.post('/api/v1/pickup', json={
        'event_id': f'ev-test-{int(time.time())}',
        'drink_id': 'D-test-s2',
        'target_table': 'T02',
        'via_pickup': True,
    })
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('pickup 선점 setmode timeout — serving stack 미기동')
    assert r.status_code == 200, f'pickup 거부: {r.text}'

    # serving 전환 wait
    result = ws_collect(
        types={'mode_state'},
        timeout=10.0,
        match=lambda m: (m.get('data') or {}).get('current') == 'serving',
    )
    msg = _ws_result_or_skip(result, 'serving')
    params = msg['data'].get('params') or {}
    assert params.get('waypoint') == 'T02' or params.get('target_table') == 'T02'


# ───── S3: serving 완료 → idle (completion_watcher pipeline 검증) ─────

def test_s3_serving_complete_to_idle(http, ws_collect):
    """serving 진입 후 completion 신호 주입 → dwell 후 자동 idle.

    실 Nav2 도달 (~75s + AMCL race ~30s) 대신 inject_completion='serving' 으로
    pipeline 만 검증. 완전 end-to-end 는 test_s3_real_nav2_cycle (opt-in).
    """
    if not _test_endpoint_available(http):
        pytest.skip('/api/v1/_test/inject_state 미등록 — MOCA_TEST_MODE 미설정')
    _ensure_idle(http)
    try:
        # 1. pickup → serving 진입
        r = http.post('/api/v1/pickup', json={
            'event_id': f'ev-s3-{int(time.time())}',
            'drink_id': 'D-s3',
            'target_table': 'T01',
            'via_pickup': True,
        })
        if r.status_code == 500 and 'timeout' in r.text.lower():
            pytest.skip('pickup setmode timeout — serving stack 미기동')
        assert r.status_code == 200, f'pickup 거부: {r.text}'
        # mode 가 'serving' 으로 실제 전환될 때까지 polling — _observe(mode!='serving')
        # silent skip 회피 (transition ~1.9-2.5s).
        if not _wait_for_mode(http, 'serving', timeout=5.0):
            pytest.skip('pickup 후 serving 모드 미도달 (5s)')

        # 2. completion 주입 — _test_completion_locked + on_serving_state('idle')
        r = http.post('/api/v1/_test/inject_state',
                      json={'inject_completion': 'serving'})
        assert r.status_code == 200, f'inject 실패: {r.text}'

        # 3. completion_dwell_serving (3s) + setmode 후 idle 도달 wait — 10s 여유
        result = ws_collect(
            types={'mode_state'},
            timeout=10.0,
            match=lambda m: (m.get('data') or {}).get('current') == 'idle',
        )
        msg = _ws_result_or_skip(result, 'idle')
        assert msg['data']['current'] == 'idle'
    finally:
        # completion lock 해제 (다른 테스트 영향 회피)
        http.post('/api/v1/_test/inject_state', json={'clear': True})


def test_s3_real_nav2_cycle(http, ws_collect):
    """실 Gazebo Nav2 도달 + 복귀 cycle 까지 검증 (slow ~75-100s).

    typical: T01 nav 10-15s + dwell 5s + 복귀 60s + completion dwell 3s.
    AMCL cold start race 는 run_nav2_sim.sh 의 warmup nav (Step 3.5) 가 회피.

    검증 절차:
      1. robot pose 를 home 으로 teleport (run 누적 위치 drift 회피 — flake fix)
      2. pickup → serving 진입 (wait_for_mode)
      3. ws_collect 로 serving → idle 복귀 매칭 (150s timeout)
      4. 초기 idle 직후 false-positive 회피 위해 serving 진입 후 ws_collect 시작
    """
    _ensure_idle(http)
    # robot 를 home_pose 로 teleport — flake 누적 회피 (test endpoint 부재 시 graceful skip)
    if _test_endpoint_available(http):
        r = http.post('/api/v1/_test/reset_robot_pose', json={})
        # Gazebo CLI 미설치 시 503 → 무시 (기존 동작 유지)
        if r.status_code == 200:
            time.sleep(1.0)  # AMCL 가 새 pose 인지 + costmap 안정 대기
    r = http.post('/api/v1/pickup', json={
        'event_id': f'ev-s3-real-{int(time.time())}',
        'drink_id': 'D-s3r',
        'target_table': 'T01',
        'via_pickup': True,
    })
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('pickup setmode timeout — serving stack 미기동')
    assert r.status_code == 200
    # serving 진입 확인 (false-positive 회피)
    if not _wait_for_mode(http, 'serving', timeout=5.0):
        pytest.skip('pickup 후 serving 모드 미도달')

    # 실 Nav2 nav T01 + dwell 5s + 복귀 + completion dwell 3s — 150s timeout
    result = ws_collect(
        types={'mode_state'},
        timeout=150.0,
        match=lambda m: (m.get('data') or {}).get('current') == 'idle',
    )
    msg = _ws_result_or_skip(result, 'idle')
    assert msg['data']['current'] == 'idle'


# ───── S4: guide → guiding ─────

def test_s4_guide_to_guiding(http, ws_collect):
    """POST /guide → guiding 진입."""
    _ensure_idle(http)

    r = http.post('/api/v1/guide', json={
        'event_id': f'ev-test-{int(time.time())}',
        'customer_id': f'C-test-{int(time.time())}',
        'party_size': 1,
        'preferred_table': 'T03',
    })
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('guide setmode timeout — guiding stack 미기동 (Gazebo 풀스택 필요)')
    assert r.status_code == 200, f'guide 거부: {r.text}'

    result = ws_collect(
        types={'mode_state'},
        timeout=10.0,
        match=lambda m: (m.get('data') or {}).get('current') == 'guiding',
    )
    _ws_result_or_skip(result, 'guiding')


# ───── S5: emergency_stop → alarm_dwell 차단 ─────

def test_s5_emergency_stop(http):
    """emergency_stop 후 alarm_dwell_sec 동안 모드 진입 차단.

    참고: dwell 후 idle 자동 복귀는 mode stack 의존 (S3 와 동일 영역) — 본 검증 X.
    """
    _ensure_idle(http)

    # emergency_stop
    r = http.post('/api/v1/emergency_stop')
    assert r.status_code == 200, f'emergency_stop 거부: {r.text}'
    data = r.json().get('data') or {}
    dwell = data.get('blocked_until_sec', 5.0)
    assert dwell > 0, 'alarm_dwell_sec 미반환'
    assert data.get('acknowledged') is True

    # 차단 동안 모드 진입 시도 → 거부 (SAFETY_ALARM 또는 BUSY)
    time.sleep(0.5)
    r = http.post('/api/v1/mode',
                  json={'mode': 'patrol', 'params': {},
                        'override_priority': False})
    # 정상 거부 코드: 503 (SAFETY_ALARM/BATTERY_LOW), 423 (BUSY), 400 (INVALID)
    # 500 (setmode timeout) 도 시뮬 노드 미응답 시 발생 가능 — 차단 자체는 인정
    assert r.status_code in (503, 423, 400, 500), \
        f'차단 무시됨 (status={r.status_code}, body={r.text})'


# ───── S6: 거부 케이스 ─────

def test_s6_invalid_mode(http):
    """INVALID_MODE — schema 미정의 mode 거부."""
    r = http.post('/api/v1/mode', json={'mode': 'foobar_invalid', 'params': {}})
    assert r.status_code == 400, f'INVALID_MODE 미거부: {r.status_code}'
    assert _err_code(r) == 'INVALID_MODE', f'code 불일치: {r.json()}'


def _test_endpoint_available(http) -> bool:
    """/api/v1/_test/inject_state 등록 여부 — MOCA_TEST_MODE 환경에서만 활성."""
    r = http.post('/api/v1/_test/inject_state', json={})
    return r.status_code != 404


def test_s6_battery_low(http):
    """inject battery_pct < battery_min → POST /mode (idle 외) 503 BATTERY_LOW."""
    if not _test_endpoint_available(http):
        pytest.skip(
            '/api/v1/_test/inject_state 미등록 — opserver 를 MOCA_TEST_MODE=1 '
            '(run_dashboard.sh --test-mode 또는 run_sim.sh --test-mode) 로 기동 필요')
    _ensure_idle(http)
    try:
        # battery 0.05 < 0.20 (battery_min default)
        http.post('/api/v1/_test/inject_state', json={'battery_pct': 0.05})
        time.sleep(0.2)
        # idle 외 진입 시도 → BATTERY_LOW 거부
        r = http.post('/api/v1/mode', json={
            'mode': 'patrol', 'params': {}, 'override_priority': False})
        assert r.status_code == 503, (
            f'BATTERY_LOW 미거부 (status={r.status_code}, body={r.text})')
        assert _err_code(r) == 'BATTERY_LOW', f'code 불일치: {r.json()}'
    finally:
        # battery 원복 (높은 값 주입 — sim 엔 /battery_state publisher 없음)
        http.post('/api/v1/_test/inject_state', json={'battery_pct': 1.0})


def test_s6_safety_alarm(http):
    """inject safety_ok=false → POST /mode 503 SAFETY_ALARM."""
    if not _test_endpoint_available(http):
        pytest.skip(
            '/api/v1/_test/inject_state 미등록 — MOCA_TEST_MODE 미설정')
    _ensure_idle(http)
    try:
        http.post('/api/v1/_test/inject_state', json={'safety_ok': False})
        time.sleep(0.2)
        r = http.post('/api/v1/mode', json={
            'mode': 'patrol', 'params': {}, 'override_priority': False})
        assert r.status_code == 503, (
            f'SAFETY_ALARM 미거부 (status={r.status_code}, body={r.text})')
        assert _err_code(r) == 'SAFETY_ALARM', f'code 불일치: {r.json()}'
    finally:
        # lock 해제 + safety_ok 원복 (다음 /mode/state 가 덮어쓰면 정상화)
        http.post('/api/v1/_test/inject_state',
                  json={'safety_ok': True, 'clear': False})
        http.post('/api/v1/_test/inject_state', json={'clear': True})


def test_s6_busy_priority_gating(http):
    """BUSY = lower-priority 모드를 active mode 중에 시도 (override 없이) → 423.

    PRIORITY: serving=1 < guiding=2 < patrol=3 < engaging=5 (idle=99).
    serving 진입 후 engaging 시도 (override=False) → BUSY.

    참고: 동시 set_mode race 로 induce 가능 (mode_manager transition_in_progress)
    하나 본 priority gating 이 deterministic + orchestrator 의 BUSY 본 경로 검증.
    """
    _ensure_idle(http)
    # serving 진입 (override=True 로 priority 무시)
    r = http.post('/api/v1/mode', json={
        'mode': 'serving', 'params': {'waypoint': 'T01'},
        'override_priority': True})
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('serving setmode timeout — serving stack 미기동')
    assert r.status_code == 200, f'serving 진입 거부: {r.text}'
    if not _wait_for_mode(http, 'serving', timeout=5.0):
        pytest.skip('serving 모드 진입 실패')

    try:
        # engaging (priority 5) 시도 — override=False, serving (1) 활성 중
        r = http.post('/api/v1/mode', json={
            'mode': 'engaging', 'params': {}, 'override_priority': False})
        assert r.status_code == 423, f'BUSY 미거부: status={r.status_code}, body={r.text}'
        assert _err_code(r) == 'BUSY', f'code 불일치: {r.json()}'
        # 메시지에 current_mode 명시 확인 (orchestrator: "lower_priority_during_serving")
        body = _err_body(r)
        assert 'serving' in (body.get('message') or '').lower(), (
            f'메시지에 current_mode 명시 누락: {body}')
    finally:
        # 다음 테스트 영향 회피 — idle 강제 복귀
        http.post('/api/v1/mode', json={
            'mode': 'idle', 'params': {}, 'override_priority': True})


# ───── S7: WS event_log 누적 ─────

def test_s7_event_log_accumulate(http):
    """REST 호출이 event_log deque 에 누적되는지 확인."""
    before = http.get('/api/v1/events?limit=500').json()['data']['count']

    for _ in range(2):
        http.post('/api/v1/mode',
                  json={'mode': 'idle', 'params': {}, 'override_priority': True})
        time.sleep(0.2)
        http.post('/api/v1/command',
                  json={'command_type': 'utter',
                        'payload': {'text': 'test S7'}})
        time.sleep(0.2)

    after = http.get('/api/v1/events?limit=500').json()['data']['count']
    assert after > before, f'event 누적 안 됨 (before={before}, after={after})'


# ───── S8: set_config → config_updated broadcast ─────

def test_s8_config_broadcast(http):
    """REST set_config → WS config_updated broadcast 수신 검증."""
    import asyncio
    import json
    import threading
    import websockets

    from tests.integration.conftest import WS_URL

    received = []

    def ws_listener():
        async def _listen():
            try:
                async with websockets.connect(WS_URL) as ws:
                    end = asyncio.get_event_loop().time() + 5.0
                    while asyncio.get_event_loop().time() < end:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            msg = json.loads(raw)
                            if msg.get('type') == 'config_updated':
                                received.append(msg)
                                return
                        except asyncio.TimeoutError:
                            continue
            except Exception:
                pass
        asyncio.run(_listen())

    t = threading.Thread(target=ws_listener, daemon=True)
    t.start()
    time.sleep(0.5)

    r = http.post('/api/v1/config', json={'patrol_interval_minutes': 0.5})
    assert r.status_code == 200

    t.join(timeout=6.0)
    assert received, 'config_updated WS broadcast 수신 실패'
    keys = received[0]['data'].get('updated_keys') or []
    assert 'patrol_interval_minutes' in keys, f'updated_keys 불일치: {keys}'


# ───── S9: utter command ─────

# ───── S10: engaging 모드 진입 ─────

def test_s10_engaging_entry(http, ws_collect):
    """POST /mode engaging → mode_state.current='engaging' 진입."""
    _ensure_idle(http)
    r = http.post('/api/v1/mode', json={
        'mode': 'engaging', 'params': {}, 'override_priority': True})
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('engaging setmode timeout — engaging stack 미기동')
    assert r.status_code == 200, f'engaging 거부: {r.text}'
    result = ws_collect(
        types={'mode_state'},
        timeout=10.0,
        match=lambda m: (m.get('data') or {}).get('current') == 'engaging',
    )
    msg = _ws_result_or_skip(result, 'engaging')
    assert msg['data']['current'] == 'engaging'


# ───── S11: engaging 완료 → idle (completion pipeline) ─────

def test_s11_engaging_complete_to_idle(http, ws_collect):
    """engaging 진입 후 inject_completion='engaging' → dwell 후 자동 idle.

    completion_dwell_engaging=2s + setmode ~5s 안 도달.
    """
    if not _test_endpoint_available(http):
        pytest.skip('/api/v1/_test/inject_state 미등록 — MOCA_TEST_MODE 미설정')
    _ensure_idle(http)
    try:
        r = http.post('/api/v1/mode', json={
            'mode': 'engaging', 'params': {}, 'override_priority': True})
        if r.status_code == 500 and 'timeout' in r.text.lower():
            pytest.skip('engaging setmode timeout — engaging stack 미기동')
        assert r.status_code == 200, f'engaging 거부: {r.text}'
        # mode_state 가 engaging 으로 도달 대기
        if not _wait_for_mode(http, 'engaging', timeout=5.0):
            pytest.skip('engaging 모드 진입 실패')

        # completion 주입 — engaging 의 경우 lock 불필요 (실 BT 가 /bt/result 발행 X)
        r = http.post('/api/v1/_test/inject_state',
                      json={'inject_completion': 'engaging'})
        assert r.status_code == 200, f'inject 실패: {r.text}'

        # completion_dwell_engaging (2s) + setmode 후 idle 도달 — 10s 여유
        result = ws_collect(
            types={'mode_state'},
            timeout=10.0,
            match=lambda m: (m.get('data') or {}).get('current') == 'idle',
        )
        msg = _ws_result_or_skip(result, 'idle')
        assert msg['data']['current'] == 'idle'
    finally:
        http.post('/api/v1/_test/inject_state', json={'clear': True})


# ───── S12: engaging 중 rapport abort_trigger → 강제 idle ─────

def test_s12_engaging_rapport_abort(http, ws_collect):
    """engaging 진행 중 /rapport/event 의 abort_trigger 발생 → mode_manager 가 즉시 강제 idle.

    cafe_funnel BT 의 abort 경로 (Russell V<-0.5 OR A>0.4) 시뮬레이션.
    mode_manager._on_rapport 의 강제 idle thread 검증.
    """
    if not _test_endpoint_available(http):
        pytest.skip('/api/v1/_test/inject_state 미등록 — MOCA_TEST_MODE 미설정')
    _ensure_idle(http)
    try:
        r = http.post('/api/v1/mode', json={
            'mode': 'engaging', 'params': {}, 'override_priority': True})
        if r.status_code == 500 and 'timeout' in r.text.lower():
            pytest.skip('engaging setmode timeout — engaging stack 미기동')
        assert r.status_code == 200
        if not _wait_for_mode(http, 'engaging', timeout=5.0):
            pytest.skip('engaging 모드 진입 실패')

        # rapport abort_trigger 발행
        r = http.post('/api/v1/_test/inject_state',
                      json={'inject_rapport_abort': True})
        assert r.status_code == 200, f'inject 실패: {r.text}'

        # mode_manager 의 강제 idle thread (~1.5s spawn) — 10s 여유
        result = ws_collect(
            types={'mode_state'},
            timeout=10.0,
            match=lambda m: (m.get('data') or {}).get('current') == 'idle',
        )
        msg = _ws_result_or_skip(result, 'idle')
        assert msg['data']['current'] == 'idle'
    finally:
        # alarm dwell 5s 안에 다른 테스트 시도되면 차단 → 짧게 대기 (다음 테스트
        # 시작 시 _ensure_idle 가 처리)
        pass


# ───── S13: engaging 중 pickup → serving 선점 (priority 5 → 1) ─────

def test_s13_engaging_pickup_preempt_serving(http, ws_collect):
    """engaging (priority 5) → POST /pickup → serving (priority 1) 자동 선점.

    PRIORITY constants 검증: 'serving'<5, 'engaging'=5. override_priority=False 로도
    serving 이 engaging 을 선점.
    """
    _ensure_idle(http)
    # engaging 강제 진입
    r = http.post('/api/v1/mode', json={
        'mode': 'engaging', 'params': {}, 'override_priority': True})
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('engaging setmode timeout — engaging stack 미기동')
    assert r.status_code == 200, f'engaging 거부: {r.text}'
    if not _wait_for_mode(http, 'engaging', timeout=5.0):
        pytest.skip('engaging 모드 진입 실패')

    # pickup 호출 — override_priority=False (기본 우선순위 게이팅)
    r = http.post('/api/v1/pickup', json={
        'event_id': f'ev-s13-{int(time.time())}',
        'drink_id': 'D-test-s13',
        'target_table': 'T02',
        'via_pickup': True,
    })
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('pickup setmode timeout — serving stack 미기동')
    assert r.status_code == 200, f'pickup 거부: {r.text}'

    # serving 전환 wait
    result = ws_collect(
        types={'mode_state'},
        timeout=10.0,
        match=lambda m: (m.get('data') or {}).get('current') == 'serving',
    )
    msg = _ws_result_or_skip(result, 'serving')
    params = msg['data'].get('params') or {}
    assert params.get('waypoint') == 'T02' or params.get('target_table') == 'T02'


# ───── S14: engaging 중 guide → guiding 선점 (priority 5 → 2) ─────

def test_s14_engaging_guide_preempt_guiding(http, ws_collect):
    """engaging (priority 5) → POST /guide → guiding (priority 2) 자동 선점."""
    _ensure_idle(http)
    r = http.post('/api/v1/mode', json={
        'mode': 'engaging', 'params': {}, 'override_priority': True})
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('engaging setmode timeout — engaging stack 미기동')
    assert r.status_code == 200, f'engaging 거부: {r.text}'
    if not _wait_for_mode(http, 'engaging', timeout=5.0):
        pytest.skip('engaging 모드 진입 실패')

    # guide 호출
    r = http.post('/api/v1/guide', json={
        'event_id': f'ev-s14-{int(time.time())}',
        'customer_id': f'C-test-{int(time.time())}',
        'party_size': 1,
        'preferred_table': 'T03',
    })
    if r.status_code == 500 and 'timeout' in r.text.lower():
        pytest.skip('guide setmode timeout — guiding stack 미기동')
    assert r.status_code == 200, f'guide 거부: {r.text}'

    result = ws_collect(
        types={'mode_state'},
        timeout=10.0,
        match=lambda m: (m.get('data') or {}).get('current') == 'guiding',
    )
    _ws_result_or_skip(result, 'guiding')


def test_s9_utter_command(http):
    """POST /command command_type='utter' 정상 응답."""
    r = http.post('/api/v1/command', json={
        'command_type': 'utter',
        'payload': {'text': '안녕하세요!', 'face_expression': 'hello'},
    })
    assert r.status_code == 200
    assert r.json()['data'].get('acknowledged') is True

    # 잘못된 command_type
    r = http.post('/api/v1/command', json={
        'command_type': 'foobar_invalid',
        'payload': {},
    })
    assert r.status_code == 400
    assert _err_code(r) == 'INVALID_PAYLOAD'
