"""conftest.py — 운영 UI 자동 시나리오 통합테스트 공통 fixture.

전제: bash scripts/run_sim.sh 로 Gazebo + Nav2 + 운영 UI 풀스택이 사전 기동된 상태.
opserver health 응답 없으면 모든 테스트 skip.
"""

import asyncio
import os
import time

import httpx
import pytest


BASE_URL = os.environ.get('MOCA_OPSERVER_URL', 'http://localhost:8800')
WS_URL = BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/dashboard'


@pytest.fixture(scope='session')
def opserver_alive():
    """opserver health check — 미응답 시 모든 테스트 skip."""
    try:
        r = httpx.get(f'{BASE_URL}/api/v1/health', timeout=3.0)
        if r.status_code != 200:
            pytest.skip(f'opserver health 비정상: {r.status_code}')
    except httpx.RequestError as e:
        pytest.skip(
            f'opserver 미접속 ({BASE_URL}). '
            f'사전 기동 필요: bash scripts/run_sim.sh. 원인: {e}')


@pytest.fixture
def http(opserver_alive):
    """동기 httpx Client (per-test scope)."""
    with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
        yield client


def _drain_until_clean(http, max_iters=8, settle_sec=2.5):
    """serving 큐 잔존 entry 가 idle 진입 시 자동 재트리거 (_drain_serving_queue).
    S1 의 idle dwell 보장 위해, mode 가 idle 이고 큐가 빌 때까지 반복.
    이미 클린이면 즉시 return — 불필요한 POST 로 transition_in_progress 충돌 회피.
    """
    for _ in range(max_iters):
        # 먼저 상태 확인
        try:
            snap = http.get('/api/v1/status').json()['data']
            q = (snap.get('queue') or {}).get('serving') or []
            mode = (snap.get('mode') or {}).get('current')
            if not q and mode == 'idle':
                return  # 이미 클린
        except Exception:
            return
        # 더러우면 idle 강제 (500 timeout 은 mode_manager 가 spawn 중이라 잠시 후 재시도)
        try:
            http.post('/api/v1/mode', json={
                'mode': 'idle', 'params': {}, 'override_priority': True})
        except Exception:
            pass
        time.sleep(settle_sec)   # mode_manager spawn ~1.5s + drain tick 1s 여유


@pytest.fixture
def fast_patrol(http):
    """patrol_interval_minutes 를 0.1 (6초) 로 임시 단축 + business_hours 24/7 + teardown 원복.

    시나리오 S1 (idle 5분 → patrol) 을 실시간 5분 안 기다리고 검증.
    business_hours 도 임시 override — 야간 실행 (현재 시각 영업 외) 에서도 patrol 트리거 가능하도록.
    serving queue 잔존 시 idle dwell 이 깨지므로 사전 drain.
    """
    # 잔존 serving queue 정리 (다른 테스트 잔재 — drain bug 회피)
    _drain_until_clean(http)

    # 현재 값 조회
    r = http.get('/api/v1/config')
    r.raise_for_status()
    cur = r.json().get('data', {})
    orig_interval = cur.get('patrol_interval_minutes', 5.0)
    orig_hours = cur.get('business_hours', '09:00-22:00')

    orig_cooldown = cur.get('patrol_retrigger_cooldown_sec', 30.0)

    # 0.1 분 (6초) + 24/7 + cooldown 0 (반복 실행 시 30s 대기 회피)
    r = http.post('/api/v1/config', json={
        'patrol_interval_minutes': 0.1,
        'business_hours': '24/7',
        'patrol_retrigger_cooldown_sec': 0.0,
    })
    r.raise_for_status()
    time.sleep(0.5)   # broadcast + idle_patrol_timer 반영 대기

    yield 0.1 * 60.0   # seconds — 테스트가 이걸 기다림 (6초)

    # 원복
    try:
        http.post('/api/v1/config', json={
            'patrol_interval_minutes': orig_interval,
            'business_hours': orig_hours,
            'patrol_retrigger_cooldown_sec': orig_cooldown,
        })
    except Exception:
        pass


@pytest.fixture
def force_idle(http):
    """테스트 시작 시 idle 강제 진입 (clean state)."""
    try:
        http.post('/api/v1/mode',
                  json={'mode': 'idle', 'params': {}, 'override_priority': True})
        time.sleep(0.5)
    except Exception:
        pass
    yield


# ───── async WS 헬퍼 ─────

async def _ws_wait_for(types, timeout=10.0, match=None):
    """WS 연결 후 expected types 의 메시지 수집. match 가 있으면 첫 매칭 즉시 반환.

    Args:
        types: 수신 대기할 메시지 type set (예: {'mode_state', 'set_mode_result'})
        timeout: 전체 wait timeout (초)
        match: (msg) -> bool callable. True 시 즉시 반환. 없으면 timeout 까지 누적.

    Returns:
        match 모드: 매칭 msg
        누적 모드: list[msg]
    """
    import json
    import websockets
    msgs = []
    try:
        async with websockets.connect(WS_URL) as ws:
            end = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = end - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get('type') in types:
                    msgs.append(msg)
                    if match and match(msg):
                        return msg
    except Exception as e:
        raise RuntimeError(f'WS 연결/수신 실패: {e}')
    return msgs


def ws_wait_for(types, timeout=10.0, match=None):
    """sync wrapper for _ws_wait_for. asyncio.run 으로 호출."""
    return asyncio.run(_ws_wait_for(types, timeout=timeout, match=match))


@pytest.fixture
def ws_collect():
    """fixture 형태로 ws_wait_for 전달."""
    return ws_wait_for
