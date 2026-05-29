"""rest_api.py — FastAPI 라우터.

API 사양: docs/moca_opserver_api_spec.md §2.

M1 단계 구현 엔드포인트:
  GET  /api/v1/health           — 헬스체크 (ROS 무관)
  GET  /api/v1/status           — 종합 상태 (모드/배터리/큐/테이블)
  GET  /api/v1/tables           — 테이블 점유 현황 (M1 빈 데이터)
  POST /api/v1/order            — POS 주문 접수 (큐 등록만, 모드 X)
  POST /api/v1/pickup           — OpenARM 제조완료 → serving 트리거
  POST /api/v1/guide            — POS 동행 안내 요청 → guiding 트리거 (M2 본격 구현)
  POST /api/v1/mode             — 운영자 수동 모드 전환
  POST /api/v1/command          — 운영자 미세 제어 (utter / express / skip_table / resume)
  POST /api/v1/emergency_stop   — 비상정지
  WS   /ws/dashboard            — WebSocket 대시보드 채널

인증 (M3): X-API-Key / X-Operator-Token 헤더. M1 은 enabled=False.
"""

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .schemas import (
    ApiError, ApiResponse,
    CommandRequest, ConfigRequest, GuideRequest, ModeRequest, OrderRequest,
    PickupRequest,
)
from .ws_hub import now_iso


log = logging.getLogger(__name__)

VALID_TABLES = ('T01', 'T02', 'T03', 'T04', 'T05')


def _ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    return ApiResponse(data=data or {}, ts=now_iso()).model_dump()


def _err(code: str, message: str, status_code: int = 400):
    raise HTTPException(
        status_code=status_code,
        detail=ApiError(code=code, message=message, ts=now_iso()).model_dump(),
    )


def build_fastapi_app(opserver) -> FastAPI:
    """opserver 노드 인스턴스를 클로저로 잡아 라우터를 구성.

    opserver 가 노출해야 할 속성/메서드:
      current_mode, battery_pct, robot_online, config
      orchestrator (ModeOrchestrator)
      ws_hub (WsHub)
      event_queue (EventQueue, 선택)
      publish_op_event(source, event_type, payload_dict, outcome)
      publish_operator_command(command_type, payload_dict)
      publish_serving_goto_table(table_id)
      get_status_snapshot() -> dict
      get_tables_snapshot() -> list
    """
    app = FastAPI(title='moca opserver', version='0.1.0')

    # CORS / 보안 헤더는 M3 에서.

    @app.get('/api/v1/health')
    def health():
        return _ok({
            'opserver_version': '0.1.0',
            'uptime_sec': opserver.uptime_sec(),
        })

    @app.get('/api/v1/status')
    def status():
        return _ok(opserver.get_status_snapshot())

    @app.get('/api/v1/tables')
    def tables():
        return _ok({
            'tables': opserver.get_tables_snapshot(),
            'last_patrol_completed_at': opserver.last_patrol_completed_at(),
        })

    @app.get('/api/v1/ntp')
    def get_ntp_status():
        """시간 동기화 상태.

        chrony 설치 시 chronyc tracking 우선, 미설치 시 timedatectl 파싱.
        5090 LAN 마스터 (192.168.0.133) ICMP reach 측정.
        다른 5대 통합 표시는 reporter/ssh exec 필요 — 본 endpoint 는 운영 노트북 자체 상태만.
        """
        import shutil
        import subprocess
        import re
        import time as _time

        result = {
            'tool': None,
            'synchronized': None,
            'server': None,
            'server_ip': None,
            'tz': None,
            'now_utc': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
            'warnings': [],
        }

        if shutil.which('chronyc'):
            result['tool'] = 'chrony'
            try:
                out = subprocess.run(
                    ['chronyc', 'tracking'],
                    capture_output=True, text=True, timeout=2.0).stdout
                for line in out.splitlines():
                    if ':' not in line:
                        continue
                    k, v = line.split(':', 1)
                    k, v = k.strip(), v.strip()
                    if k == 'Reference ID':
                        result['server'] = v
                    elif k == 'Stratum':
                        try:
                            result['stratum'] = int(v)
                        except Exception:
                            pass
                    elif k == 'Last offset':
                        result['last_offset_sec'] = v
                    elif k == 'RMS offset':
                        result['rms_offset_sec'] = v
                    elif k == 'Leap status':
                        result['synchronized'] = 'Normal' in v
            except Exception as e:
                result['warnings'].append(f'chronyc tracking 실패: {e}')

        elif shutil.which('timedatectl'):
            result['tool'] = 'systemd-timesyncd'
            try:
                out = subprocess.run(
                    ['timedatectl', 'show'],
                    capture_output=True, text=True, timeout=2.0).stdout
                for line in out.splitlines():
                    if '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    v = v.strip()
                    if k == 'NTPSynchronized':
                        result['synchronized'] = (v == 'yes')
                    elif k == 'NTP':
                        result['ntp_service_active'] = (v == 'yes')
                    elif k == 'Timezone':
                        result['tz'] = v
                # show-timesync 로 server 정보
                out2 = subprocess.run(
                    ['timedatectl', 'show-timesync', '--all'],
                    capture_output=True, text=True, timeout=2.0).stdout
                for line in out2.splitlines():
                    if '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    v = v.strip()
                    if k == 'ServerName' and v:
                        result['server'] = v
                    elif k == 'ServerAddress' and v:
                        result['server_ip'] = v
                    elif k == 'PollIntervalUSec':
                        try:
                            result['poll_interval_sec'] = int(v) / 1e6
                        except Exception:
                            pass
                result['warnings'].append(
                    'systemd-timesyncd 사용 중 — 인터넷 의존. '
                    'LAN-only 운영 + 6대 통합 sync 위해 chrony + 5090 마스터 권장 '
                    '(scripts/chrony/README.md 참조).')
            except Exception as e:
                result['warnings'].append(f'timedatectl 실패: {e}')
        else:
            result['warnings'].append('chronyc / timedatectl 모두 없음')

        # 5090 LAN 마스터 (192.168.0.133) ICMP reach 측정
        master_ip = '192.168.0.133'
        reach = {'host': master_ip, 'reachable': False, 'rtt_ms': None}
        try:
            r = subprocess.run(
                ['ping', '-c', '1', '-W', '1', master_ip],
                capture_output=True, text=True, timeout=2.5)
            if r.returncode == 0:
                reach['reachable'] = True
                m = re.search(r'time=([\d.]+)\s*ms', r.stdout)
                if m:
                    reach['rtt_ms'] = float(m.group(1))
        except Exception as e:
            reach['error'] = str(e)
        result['ntp_master_lan_5090'] = reach
        if not reach['reachable']:
            result['warnings'].append(
                f'LAN 마스터 5090 ({master_ip}) reach 실패 — 카페 LAN 점검.')

        return _ok(result)

    @app.get('/api/v1/events')
    def get_events(
        before: str = '',
        limit: int = 100,
        category: str = '',
        level: str = '',
    ):
        """이벤트 페이지네이션 (in-memory deque maxlen=500 안에서만).

        category / level 은 콤마 구분. before 는 ISO ts (이전 페이지 더 불러오기).
        """
        items = opserver.get_events_snapshot()
        if category:
            cats = {c.strip() for c in category.split(',') if c.strip()}
            items = [e for e in items if e.get('category', '') in cats]
        if level:
            levs = {l.strip() for l in level.split(',') if l.strip()}
            items = [e for e in items if e.get('level', '') in levs]
        if before:
            items = [e for e in items if e.get('ts', '') < before]
        # deque 는 append 순 — 최신순 정렬
        items = sorted(items, key=lambda e: e.get('ts', ''), reverse=True)
        try:
            lim = max(1, min(int(limit), 500))
        except Exception:
            lim = 100
        return _ok({'events': items[:lim], 'count': min(len(items), lim)})

    @app.post('/api/v1/order')
    def post_order(req: OrderRequest):
        # M1: 큐에 사전 등록만. SetMode 호출 없음.
        if opserver.event_seen(req.event_id):
            opserver.publish_op_event(
                source='pos', event_type='order_placed',
                payload=req.model_dump(),
                outcome='rejected:duplicate_event')
            _err('DUPLICATE_EVENT', 'event_id already processed', 409)
        opserver.event_mark(req.event_id)
        position = opserver.order_queue_register(req.model_dump())
        opserver.publish_op_event(
            source='pos', event_type='order_placed',
            payload=req.model_dump(), outcome='queued')
        return _ok({
            'order_id': req.order_id,
            'queued_position': position,
            'expected_pickup_min': 3,   # M1 stub
        })

    @app.post('/api/v1/pickup')
    def post_pickup(req: PickupRequest):
        if opserver.event_seen(req.event_id):
            _err('DUPLICATE_EVENT', 'event_id already processed', 409)
        if req.target_table not in VALID_TABLES:
            _err('INVALID_TABLE',
                 f"target_table '{req.target_table}' unknown", 400)
        opserver.event_mark(req.event_id)

        # gating 분기 (API spec §2.5 POST /pickup 핵심)
        current = opserver.current_mode or 'idle'
        if current == 'serving':
            # 큐만 추가, /serving/goto_table 토픽으로 통보
            opserver.publish_serving_goto_table(req.target_table)
            opserver.serving_queue_register(req.model_dump())
            opserver.publish_op_event(
                source='openarm', event_type='pickup_ready',
                payload=req.model_dump(),
                outcome='queued:serving_in_progress')
            return _ok({
                'drink_id': req.drink_id,
                'serving_mode_requested': False,
                'queue_position': opserver.serving_queue_size(),
                'current_mode_before': current,
                'preempted': False,
            })

        # ★ guiding_design §10 G3 정책 — guiding 진행 중 serving 선점 금지 (큐잉만)
        # 실 운영 정책: 손님 안내 중 끊김 부적절. guiding 완료 + idle 진입 시 큐 처리.
        # priority 만 보면 serving(1) < guiding(2) 으로 선점되겠지만 운영 정책이 우선.
        # 단, 운영자 수동 POST /mode (override_priority=True) 는 본 분기 미적용.
        if current == 'guiding':
            opserver.serving_queue_register(req.model_dump())
            opserver.publish_op_event(
                source='openarm', event_type='pickup_ready',
                payload=req.model_dump(),
                outcome='queued:guiding_in_progress')
            return _ok({
                'drink_id': req.drink_id,
                'serving_mode_requested': False,
                'queue_position': opserver.serving_queue_size(),
                'current_mode_before': current,
                'preempted': False,
            })

        # idle 또는 patrol/engaging → serving 시작 (via_pickup=True 이면 pickup 선행)
        # ★ 성공 시 큐 등록 불필요 — 실패 시에만 큐 등록하여 drain 이 재시도.
        result = opserver.start_serving_with_pickup(
            waypoint=req.target_table,
            via_pickup=req.via_pickup,
            trigger_source='openarm',
            has_drink=req.has_drink,
            override_priority=False,
        )

        if result['ok']:
            opserver.publish_op_event(
                source='openarm', event_type='pickup_ready',
                payload=req.model_dump(),
                outcome=f'accepted:{result.get("reason","")}')
            return _ok({
                'drink_id': req.drink_id,
                'serving_mode_requested': True,
                'queue_position': opserver.serving_queue_size(),
                'current_mode_before': current,
                'preempted': result.get('preempted', False),
            })

        # 실패 시 — pending 큐에 등록 (idle 진입 시 drain 이 재시도)
        opserver.serving_queue_register(req.model_dump())
        opserver.publish_op_event(
            source='openarm', event_type='pickup_ready',
            payload=req.model_dump(),
            outcome=f'rejected:{result.get("code","")}')
        code = result.get('code', 'INTERNAL_ERROR')
        status_map = {
            'BATTERY_LOW': 503, 'SAFETY_ALARM': 503, 'BUSY': 423,
            'ROBOT_OFFLINE': 503, 'INVALID_MODE': 400,
        }
        _err(code, result.get('message', ''), status_map.get(code, 500))

    @app.post('/api/v1/guide')
    def post_guide(req: GuideRequest):
        if opserver.event_seen(req.event_id):
            _err('DUPLICATE_EVENT', 'event_id already processed', 409)
        opserver.event_mark(req.event_id)

        # 빈 테이블 조회 (M1: registry 가 비어있으면 preferred_table 그대로 사용)
        assigned = opserver.assign_table_for_guide(req.preferred_table)
        if assigned is None:
            opserver.publish_op_event(
                source='pos', event_type='guide_request',
                payload=req.model_dump(), outcome='rejected:no_empty_table')
            _err('NO_EMPTY_TABLE', 'all tables occupied', 409)

        current = opserver.current_mode or 'idle'
        result = opserver.orchestrator.request_mode_change(
            target_mode='guiding',
            params={'target_table': assigned, 'customer_id': req.customer_id},
            trigger_source='pos',
            override_priority=False,
        )

        if result['ok']:
            opserver.publish_op_event(
                source='pos', event_type='guide_request',
                payload=req.model_dump(),
                outcome=f'accepted:{result.get("reason","")}')
            return _ok({
                'customer_id': req.customer_id,
                'assigned_table': assigned,
                'eta_sec': 20,   # M1 stub
                'preempted': result.get('preempted', False),
            })

        opserver.publish_op_event(
            source='pos', event_type='guide_request',
            payload=req.model_dump(),
            outcome=f'rejected:{result.get("code","")}')
        code = result.get('code', 'INTERNAL_ERROR')
        status_map = {
            'BATTERY_LOW': 503, 'SAFETY_ALARM': 503, 'BUSY': 423,
            'ROBOT_OFFLINE': 503, 'INVALID_MODE': 400,
        }
        _err(code, result.get('message', ''), status_map.get(code, 500))

    @app.post('/api/v1/mode')
    def post_mode(req: ModeRequest):
        current = opserver.current_mode or 'idle'
        result = opserver.orchestrator.request_mode_change(
            target_mode=req.mode,
            params=req.params,
            trigger_source='operator',
            override_priority=req.override_priority,
        )
        opserver.publish_op_event(
            source='operator', event_type='manual_mode',
            payload=req.model_dump(),
            outcome=('accepted' if result['ok'] else
                     f'rejected:{result.get("code","")}'))
        if result['ok']:
            return _ok({
                'current_mode_before': current,
                'current_mode_after': result.get('current_mode_after', req.mode),
                'reason': result.get('reason', ''),
            })
        code = result.get('code', 'INTERNAL_ERROR')
        status_map = {
            'BATTERY_LOW': 503, 'SAFETY_ALARM': 503, 'BUSY': 423,
            'ROBOT_OFFLINE': 503, 'INVALID_MODE': 400,
        }
        _err(code, result.get('message', ''), status_map.get(code, 500))

    @app.post('/api/v1/command')
    def post_command(req: CommandRequest):
        valid = ('utter', 'express', 'skip_table', 'resume')
        if req.command_type not in valid:
            _err('INVALID_PAYLOAD',
                 f"command_type must be one of {valid}", 400)
        opserver.publish_operator_command(req.command_type, req.payload)
        opserver.publish_op_event(
            source='operator', event_type=f'command:{req.command_type}',
            payload=req.model_dump(), outcome='accepted')
        return _ok({'acknowledged': True})

    @app.post('/api/v1/emergency_stop')
    def post_emergency_stop():
        opserver.publish_operator_command('stop_emergency', {})
        opserver.publish_op_event(
            source='operator', event_type='emergency_stop',
            payload={}, outcome='accepted')
        return _ok({
            'acknowledged': True,
            'blocked_until_sec': opserver.config.alarm_dwell_sec,
        })

    @app.post('/api/v1/config')
    def post_config(req: ConfigRequest):
        updated = opserver.update_config(req.model_dump(exclude_none=True))
        opserver.publish_op_event(
            source='operator', event_type='config_update',
            payload=req.model_dump(exclude_none=True), outcome='accepted')
        # WS broadcast
        opserver.ws_broadcast('config_updated', {'updated_keys': updated})
        return _ok({'updated_keys': updated})

    @app.get('/api/v1/config')
    def get_config():
        return _ok(opserver.config.snapshot())

    # ---------- launch helper — 외부 GUI 도구 spawn ----------

    @app.post('/api/v1/launch/map_picker')
    def launch_map_picker():
        """`scripts/place_furniture_picker.py` (tkinter GUI) 를 노트북 X11
        디스플레이에 spawn. 이미 실행 중이면 PID 만 반환.
        """
        import subprocess
        import sys
        from pathlib import Path

        # 워크스페이스 추정 — opserver_node 가 launch 된 환경 inherit
        here = Path(__file__).resolve()
        ws = None
        for parent in [here, *here.parents]:
            cand = parent / 'scripts' / 'place_furniture_picker.py'
            if cand.exists():
                ws = parent
                break
        if ws is None:
            return _err('PICKER_NOT_FOUND',
                        'scripts/place_furniture_picker.py not located', 404)

        script = ws / 'scripts' / 'place_furniture_picker.py'

        # 이미 실행 중?
        try:
            existing = subprocess.run(
                ['pgrep', '-f', 'place_furniture_picker.py'],
                capture_output=True, text=True, timeout=2.0)
            if existing.stdout.strip():
                pids = [int(p) for p in existing.stdout.strip().split('\n')
                        if p.strip().isdigit()]
                return _ok({'status': 'already_running', 'pids': pids,
                            'script': str(script)})
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        env = os.environ.copy()
        if not env.get('DISPLAY'):
            env['DISPLAY'] = ':0'

        try:
            proc = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(ws), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except Exception as e:
            return _err('PICKER_LAUNCH_FAILED', str(e), 500)

        return _ok({'status': 'launched', 'pid': proc.pid,
                    'script': str(script), 'display': env['DISPLAY']})

    # ---------- 테스트 전용 (MOCA_TEST_MODE 환경변수 게이트) ----------
    # 운영 모드에서는 등록되지 않음 → 404. 시나리오 테스트 (S6) 가 사용.

    if os.environ.get('MOCA_TEST_MODE', '').strip() in ('1', 'true', 'yes'):

        @app.post('/api/v1/_test/inject_state')
        def post_inject_state(payload: dict):
            """opserver 내부 가드 상태 직접 주입.

            허용 키:
              battery_pct: float (예: 0.05 → BATTERY_LOW 유도)
              safety_ok: bool (false 시 lock 설정 — /mode/state 덮어쓰기 차단)
              inject_completion: str ('serving'|'patrol'|'guiding'|'engaging')
                  → completion_watcher 에 done 신호 주입 → dwell 후 SetMode(idle).
                  S3 시나리오 — Nav2 실 도달 안 기다리고 pipeline 검증.
              inject_rapport_abort: bool — /rapport/event 에
                  RapportEvent(event_type='abort_trigger', weight=0.9) 발행.
                  mode_manager 가 abort_trigger 인지 → 강제 idle (S12).
              clear: bool (true 시 safety lock 해제 + battery 미설정)
            """
            applied = {}
            if 'clear' in payload and payload['clear']:
                opserver._test_safety_locked = False
                opserver._test_completion_locked = False
                # battery_pct 는 reset 불가 (sim 에 publisher 없음) — 명시 set 만 가능
                applied['cleared'] = True
            else:
                if 'battery_pct' in payload:
                    opserver.battery_pct = (
                        float(payload['battery_pct'])
                        if payload['battery_pct'] is not None else None)
                    applied['battery_pct'] = opserver.battery_pct
                if 'safety_ok' in payload:
                    opserver.safety_ok = bool(payload['safety_ok'])
                    opserver._test_safety_locked = True
                    applied['safety_ok'] = opserver.safety_ok
                    applied['safety_locked'] = True
                if 'inject_rapport_abort' in payload and payload['inject_rapport_abort']:
                    from dobi_npc_msgs.msg import RapportEvent
                    ev = RapportEvent()
                    ev.header.stamp = opserver.get_clock().now().to_msg()
                    ev.event_type = 'abort_trigger'
                    ev.weight = 0.9
                    ev.reason = 'test_inject'
                    opserver.pub_rapport.publish(ev)
                    applied['rapport_abort_published'] = True
                if 'inject_completion' in payload:
                    target = str(payload['inject_completion'])
                    # done 신호 매핑 — completion_watcher._DONE_SIGNALS 정합
                    done_signal = {
                        'serving': 'idle',
                        'patrol': 'done',
                        'guiding': 'done',
                        'engaging': 'done',
                    }.get(target)
                    if done_signal:
                        # serving 의 경우 실 dispatcher 의 stale state 가 dwell reset
                        # → lock 후 inject (clear:true 로 해제)
                        if target == 'serving':
                            opserver._test_completion_locked = True
                            applied['completion_locked'] = True
                        method = getattr(
                            opserver.completion_watcher,
                            f'on_{target}_state',
                            None)
                        if method:
                            method(done_signal)
                            applied['inject_completion'] = target
                            applied['done_signal'] = done_signal
                        elif target == 'engaging':
                            opserver.completion_watcher.on_engaging_done()
                            applied['inject_completion'] = target
            return _ok(applied)

        @app.post('/api/v1/_test/reset_robot_pose')
        def post_reset_robot_pose(payload: dict):
            """Gazebo set_pose 로 robot 을 home_pose (또는 지정 위치) 로 teleport.

            S3 real_nav2_cycle 의 robot 위치 누적 flake 회피용.
            payload 옵션: {world, model, x, y, yaw}. 기본은 tables.yaml home_pose.

            Gazebo CLI (`gz service`) 가 필요 — 미설치 시 503.
            """
            import subprocess
            import math
            world = payload.get('world', 'mapv5_moca')
            model = payload.get('model', 'vicpinky')
            x = float(payload.get('x', -36.887))
            y = float(payload.get('y', 2.809))
            yaw = float(payload.get('yaw', -1.5708))
            qz = math.sin(yaw / 2)
            qw = math.cos(yaw / 2)
            req = (f'name: "{model}", '
                   f'position: {{x: {x}, y: {y}, z: 0.0}}, '
                   f'orientation: {{z: {qz}, w: {qw}}}')
            try:
                proc = subprocess.run(
                    ['gz', 'service',
                     '-s', f'/world/{world}/set_pose',
                     '--reqtype', 'gz.msgs.Pose',
                     '--reptype', 'gz.msgs.Boolean',
                     '--timeout', '2000',
                     '--req', req],
                    capture_output=True, text=True, timeout=5.0)
            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                _err('GZ_UNAVAILABLE', str(e), 503)
            if 'data: true' in (proc.stdout or ''):
                return _ok({'pose_reset': True, 'x': x, 'y': y, 'yaw': yaw})
            _err('GZ_SET_POSE_FAILED',
                 f'stdout={proc.stdout!r} stderr={proc.stderr!r}', 503)

        print(
            '[moca_opserver] MOCA_TEST_MODE=1 — '
            '/api/v1/_test/inject_state + /api/v1/_test/reset_robot_pose 등록',
            flush=True)

    # ---------- WebSocket ----------

    @app.websocket('/ws/dashboard')
    async def ws_dashboard(ws: WebSocket):
        await opserver.ws_hub.connect(ws)
        try:
            # welcome — 현 status snapshot
            await opserver.ws_hub.send_to(
                ws, 'welcome', {'snapshot': opserver.get_status_snapshot()})

            # client → server 메시지 dispatch
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    await opserver.ws_hub.send_to(
                        ws, 'error', {'code': 'INVALID_JSON'})
                    continue
                await _dispatch_ws_message(opserver, ws, msg)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.exception(f'ws handler error: {e}')
        finally:
            await opserver.ws_hub.disconnect(ws)

    # ---------- 정적 자산 mount (moca_web_dashboard_spec.md) ----------
    # opserver share/static/ 디렉토리를 /static prefix 에 mount.
    # 빈 prefix("/") mount 는 Starlette 가 path='' 로 등록 + sub-path 매칭 안 됨 — /static 명시.
    # / 진입 시 → /static/pages/dashboard.html 리다이렉트.
    static_dir = _resolve_static_dir()
    if static_dir and os.path.isdir(static_dir):
        @app.get('/')
        def root_redirect():
            return RedirectResponse(
                url='/static/pages/dashboard.html', status_code=307)

        # follow_symlink=True 필수 — colcon symlink-install 환경에서
        # install/.../static/pages/dashboard.html 가 build → src 로 chain symlink.
        # Starlette 기본은 보안상 symlink 외부 target 거부 → 404.
        app.mount(
            '/static',
            StaticFiles(directory=static_dir, html=True, follow_symlink=True),
            name='static')
        print(
            f'[moca_opserver] static mounted /static -> {static_dir}',
            flush=True)
    else:
        print(
            f'[moca_opserver] WARN static dir not found: {static_dir!r}',
            flush=True)

    return app


def _resolve_static_dir() -> str:
    """opserver 패키지의 share/static/ 경로 — env > ament > workspace 추정.

    feedback_relative_path_convention 정합.
    """
    env = os.environ.get('MOCA_WEB_STATIC_DIR', '').strip()
    if env:
        return os.path.expanduser(env)
    # ament_index 우선
    try:
        from ament_index_python.packages import get_package_share_directory
        share = get_package_share_directory('moca_opserver')
        candidate = os.path.join(share, 'static')
        if os.path.isdir(candidate):
            return candidate
    except Exception:
        pass
    # fallback: 본 파일 위치 → ../static (symlink-install 개발 시)
    here = os.path.abspath(os.path.dirname(__file__))
    parent = os.path.dirname(here)   # src/moca_opserver/moca_opserver/ → src/moca_opserver/
    candidate = os.path.join(parent, 'static')
    if os.path.isdir(candidate):
        return candidate
    return ''


async def _dispatch_ws_message(opserver, ws: WebSocket, msg: dict) -> None:
    """WebSocket client → server 메시지 dispatch (API spec §3.4).

    REST endpoint 들을 직접 호출하지 않고 동일 로직 재사용 (orchestrator/publish).
    """
    t = msg.get('type', '')

    if t == 'set_mode':
        result = opserver.orchestrator.request_mode_change(
            target_mode=msg.get('mode', ''),
            params=msg.get('params') or {},
            trigger_source='operator_ws',
            override_priority=bool(msg.get('override_priority', False)),
        )
        await opserver.ws_hub.send_to(
            ws, 'set_mode_result', {
                'ok': result['ok'],
                'code': result.get('code'),
                'reason': result.get('reason'),
                'current_mode_after': result.get('current_mode_after'),
            })

    elif t == 'emergency_stop':
        opserver.publish_operator_command('stop_emergency', {})
        await opserver.ws_hub.send_to(ws, 'emergency_stop_ack', {})

    elif t == 'utter':
        payload = {
            'text': msg.get('text', ''),
            'face_expression': msg.get('face_expression', ''),
        }
        opserver.publish_operator_command('utter', payload)

    elif t == 'skip_table':
        opserver.publish_operator_command(
            'skip_table', {'table_id': msg.get('table_id', '')})

    elif t == 'set_config':
        updates = {k: v for k, v in msg.items()
                   if k != 'type' and v is not None}
        keys = opserver.update_config(updates)
        await opserver.ws_hub.broadcast('config_updated', {'updated_keys': keys})

    elif t == 'ack_alarm':
        # M1: ack 자체만 기록, dedup 로직은 M3
        opserver.ack_alarm(msg.get('alarm_code', ''))

    else:
        await opserver.ws_hub.send_to(
            ws, 'error', {'code': 'UNKNOWN_TYPE', 'received': t})
