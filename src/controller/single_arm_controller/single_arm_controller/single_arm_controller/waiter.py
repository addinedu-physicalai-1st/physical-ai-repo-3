"""
waiter.py — ACT 기반 ROS Action Server

모든 설정은 waiter_config.yaml에서 읽는다.
스크립트 내 하드코딩 상수는 없으며, YAML 변경만으로 동작을 제어할 수 있다.

기본 config 경로: <package_root>/config/waiter_config.yaml
ROS 파라미터: config_path  (오버라이드 가능)

serving.py와의 핵심 차이:
  ┌─────────────────────┬───────────────────────┬──────────────────────────┐
  │ 항목                │ serving.py (SmolVLA)   │ waiter.py (ACT)          │
  ├─────────────────────┼───────────────────────┼──────────────────────────┤
  │ 설정 방식           │ 스크립트 내 상수       │ YAML 파일                │
  │ 모델                │ SmolVLAPolicy (VLA)   │ ACTPolicy                │
  │ task 텍스트         │ 있음 (언어 조건부)    │ 없음 (이미지+상태만)     │
  │ prev_chunk          │ 모델에 전달            │ 사용 안 함               │
  │ Pickup/Serve 공유   │ Serve만 구현됨        │ 둘 다 동일 루프 공유     │
  └─────────────────────┴───────────────────────┴──────────────────────────┘

Sync 디버그는 build_inference_local_server.md 참고.
"""

import base64
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import requests
import rclpy as rp
import yaml
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from single_arm_controller_interfaces.action import Pickup, Serve

# 기본 config 경로: 이 파일 기준 ../config/waiter_config.yaml
_DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / 'config' / 'waiter_config.yaml')


# ── VLM 완료 판단 ─────────────────────────────────────────────────────────────

def _vlm_check_task_complete(
    image_rgb: np.ndarray,
    prompt: str,
    vlm_cfg: dict,
) -> tuple[bool, str]:
    """top 카메라 이미지를 Ollama VLM에 보내 task 완료 여부를 확인한다.

    Args:
        image_rgb: RGB uint8 (H, W, 3)
        prompt:    VLM에 보낼 완료 판단 프롬프트 (YAML에서 읽음)
        vlm_cfg:   YAML vlm 섹션 dict

    Returns:
        (complete: bool, raw_answer: str)
        VLM 응답이 "false"로 시작하면 complete=True (serving.py 동일 규약).
    """
    _, buf = cv2.imencode('.jpg', cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
    img_b64 = base64.b64encode(buf.tobytes()).decode('utf-8')

    resp = requests.post(
        f"{vlm_cfg['host']}/api/chat",
        json={
            'model':    vlm_cfg['model'],
            'messages': [{'role': 'user', 'content': prompt, 'images': [img_b64]}],
            'stream':   False,
            'options':  {'temperature': 0},
        },
        timeout=float(vlm_cfg['timeout_s']),
    )
    resp.raise_for_status()
    answer  = resp.json()['message']['content'].strip()
    complete = answer.lower().startswith('false')
    return complete, answer


# ── 설정 로드 ─────────────────────────────────────────────────────────────────

def _load_config(path: str) -> dict:
    """YAML 설정 파일을 읽어 dict로 반환한다."""
    with open(path, 'r') as f:
        cfg = yaml.safe_load(f)

    # 파생 값 계산 (memory 섹션)
    mem = cfg['memory']
    top_shape   = tuple(mem['top_shape'])
    wrist_shape = tuple(mem['wrist_shape'])
    state_dim   = mem['state_dim']
    chunk_size  = mem['chunk_size']
    action_dim  = mem['action_dim']

    mem['_top_bytes']   = int(np.prod(top_shape))
    mem['_wrist_bytes'] = int(np.prod(wrist_shape))
    mem['_state_bytes'] = state_dim * 4
    mem['_obs_bytes']   = mem['_top_bytes'] + mem['_wrist_bytes'] + mem['_state_bytes']
    mem['_act_planes']  = 2
    mem['_act_bytes']   = 2 * chunk_size * action_dim * 4

    return cfg


class _TaskComplete(Exception):
    pass


# ── ModelProcess ─────────────────────────────────────────────────────────────

class ModelProcess:
    """
    ACT 워커 프로세스를 관리한다.
    공유 메모리 크기와 워커 실행 인자를 YAML 설정에서 읽는다.
    """

    def __init__(self, cfg: dict):
        mdl = cfg['model']
        mem = cfg['memory']

        top_shape   = tuple(mem['top_shape'])
        wrist_shape = tuple(mem['wrist_shape'])
        state_dim   = mem['state_dim']
        chunk_size  = mem['chunk_size']
        action_dim  = mem['action_dim']

        obs_bytes = mem['_obs_bytes']
        act_bytes = mem['_act_bytes']
        act_planes = mem['_act_planes']

        from multiprocessing.shared_memory import SharedMemory
        self._shm_obs = SharedMemory(create=True, size=obs_bytes)
        self._shm_act = SharedMemory(create=True, size=act_bytes)

        top_bytes   = mem['_top_bytes']
        wrist_bytes = mem['_wrist_bytes']

        self._top_buf   = np.ndarray(top_shape,   dtype=np.uint8,   buffer=self._shm_obs.buf, offset=0)
        self._wrist_buf = np.ndarray(wrist_shape, dtype=np.uint8,   buffer=self._shm_obs.buf, offset=top_bytes)
        self._state_buf = np.ndarray(state_dim,   dtype=np.float32, buffer=self._shm_obs.buf, offset=top_bytes + wrist_bytes)
        self._act_buf   = np.ndarray((act_planes, chunk_size, action_dim), dtype=np.float32, buffer=self._shm_act.buf)
        self._lock = threading.Lock()

        self._sock_path   = tempfile.mktemp(prefix='act_worker_', suffix='.sock')
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(self._sock_path)
        self._server_sock.listen(1)

        worker_script = str(Path(__file__).parent / 'act_worker.py')
        config_path   = cfg.get('_config_path', _DEFAULT_CONFIG_PATH)

        self._proc = subprocess.Popen([
            mdl['python'], worker_script,
            '--model-path',   mdl['path'],
            '--device',       mdl['device'],
            '--robot-type',   mdl['robot_type'],
            '--socket-path',  self._sock_path,
            '--shm-obs-name', self._shm_obs.name,
            '--shm-act-name', self._shm_act.name,
            '--config-path',  config_path,   # act_worker가 동일 YAML로 레이아웃 동기화
        ])

        self._server_sock.settimeout(600)
        self._conn, _ = self._server_sock.accept()
        assert self._recv_exact(1) == b'R', 'Worker did not send READY'
        self._server_sock.settimeout(None)

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            data = self._conn.recv(n - len(buf))
            if not data:
                raise ConnectionError('Worker socket closed')
            buf.extend(data)
        return bytes(buf)

    def get_action_chunk(
        self,
        top_image: np.ndarray,
        wrist_image: np.ndarray,
        state: np.ndarray,
        inference_delay: int = 0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """추론 실행. 프로토콜: b'G' + uint32(delay) → b'D'"""
        with self._lock:
            np.copyto(self._top_buf,   top_image)
            np.copyto(self._wrist_buf, wrist_image)
            np.copyto(self._state_buf, state)

            self._conn.sendall(b'G' + struct.pack('>I', inference_delay))
            assert self._recv_exact(1) == b'D', 'Worker did not send DONE'

            return self._act_buf[0].copy(), self._act_buf[1].copy()

    def close(self):
        try:
            self._conn.sendall(b'Q')
        except Exception:
            pass
        self._proc.terminate()
        self._conn.close()
        self._server_sock.close()
        self._shm_obs.unlink()
        self._shm_obs.close()
        self._shm_act.unlink()
        self._shm_act.close()
        try:
            os.unlink(self._sock_path)
        except Exception:
            pass


# ── 비동기 카메라 ─────────────────────────────────────────────────────────────

class _AsyncCamera:
    """백그라운드 스레드로 cap.read()를 수행해 non-blocking read_latest() 제공."""

    def __init__(self, path: str, name: str, width: int, height: int, fps: int):
        self._name = name
        self.cap = cv2.VideoCapture(path)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS,          fps)
        if not self.cap.isOpened():
            raise RuntimeError(f'Cannot open {name} camera: {path}')

        self._frame: np.ndarray | None = None
        self._frame_time: float = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name=f'cam_{name}'
        )
        self._thread.start()

        deadline = time.time() + 5.0
        while time.time() < deadline:
            with self._lock:
                if self._frame is not None:
                    break
            time.sleep(0.01)
        else:
            self._stop.set()
            raise RuntimeError(f'{name} camera: no frame within 5s')

    def _capture_loop(self):
        while not self._stop.is_set():
            ret, frame = self.cap.read()
            if ret:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self._lock:
                    self._frame = rgb
                    self._frame_time = time.monotonic()
            elif not self._stop.is_set():
                time.sleep(0.001)

    def read_latest(self, max_age_ms: float = 1000.0) -> np.ndarray:
        with self._lock:
            if self._frame is None:
                raise RuntimeError(f'{self._name} camera: no frame')
            age_ms = (time.monotonic() - self._frame_time) * 1000.0
            if age_ms > max_age_ms:
                raise RuntimeError(f'{self._name} camera: frame too old ({age_ms:.0f}ms)')
            return self._frame.copy()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self.cap.release()


# ── 관절 정규화 ───────────────────────────────────────────────────────────────

def _make_normalizers(dxl_max: int):
    """YAML의 dxl_max로부터 정규화 함수 생성."""
    def raw_to_norm(raw):
        return (raw / dxl_max) * 200.0 - 100.0

    def norm_to_raw(norm):
        return int(((min(100.0, max(-100.0, norm)) + 100.0) / 200.0) * dxl_max)

    def raw_to_grip(raw):
        return (raw / dxl_max) * 100.0

    def grip_to_raw(norm):
        return int((min(100.0, max(0.0, norm)) / 100.0) * dxl_max)

    return raw_to_norm, norm_to_raw, raw_to_grip, grip_to_raw


# ── 로봇 드라이버 ─────────────────────────────────────────────────────────────

class _OMXRobot:
    _ADDR_TORQUE      = 64
    _ADDR_GOAL_POS    = 116
    _ADDR_PRESENT_POS = 132
    _LEN_POS          = 4

    def __init__(self, cfg: dict):
        rob = cfg['robot']
        self._motor_ids = rob['motor_ids']
        (self._raw_to_norm, self._norm_to_raw,
         self._raw_to_grip, self._grip_to_raw) = _make_normalizers(rob['dxl_max'])

        from dynamixel_sdk import (
            PortHandler, PacketHandler,
            GroupSyncRead, GroupSyncWrite, COMM_SUCCESS,
        )
        self._OK = COMM_SUCCESS
        self.port = PortHandler(rob['port'])
        self.pkt  = PacketHandler(float(rob['protocol']))
        if not self.port.openPort():
            raise RuntimeError(f"Cannot open {rob['port']}")
        if not self.port.setBaudRate(rob['baud']):
            raise RuntimeError(f"Cannot set baud {rob['baud']}")
        self.sync_read  = GroupSyncRead(self.port, self.pkt, self._ADDR_PRESENT_POS, self._LEN_POS)
        self.sync_write = GroupSyncWrite(self.port, self.pkt, self._ADDR_GOAL_POS, self._LEN_POS)
        for mid in self._motor_ids:
            self.sync_read.addParam(mid)
            self.pkt.write1ByteTxRx(self.port, mid, self._ADDR_TORQUE, 1)

    def get_positions(self) -> np.ndarray:
        self.sync_read.txRxPacket()
        values = []
        for i, mid in enumerate(self._motor_ids):
            raw = self.sync_read.getData(mid, self._ADDR_PRESENT_POS, self._LEN_POS)
            values.append(self._raw_to_grip(raw) if i == 5 else self._raw_to_norm(raw))
        return np.array(values, dtype=np.float32)

    def set_positions(self, norm: np.ndarray):
        self.sync_write.clearParam()
        for i, (mid, n) in enumerate(zip(self._motor_ids, norm)):
            raw = self._grip_to_raw(float(n)) if i == 5 else self._norm_to_raw(float(n))
            self.sync_write.addParam(mid, [(raw >> (8 * j) & 0xFF) for j in range(4)])
        self.sync_write.txPacket()

    def return_to_position(self, target: np.ndarray, duration_s: float = 3.0, fps: int = 50):
        current = self.get_positions()
        steps   = max(int(duration_s * fps), 1)
        period  = 1.0 / fps
        for step in range(1, steps + 1):
            t = step / steps
            self.set_positions(current * (1 - t) + target * t)
            time.sleep(period)

    def close(self):
        for mid in self._motor_ids:
            self.pkt.write1ByteTxRx(self.port, mid, self._ADDR_TORQUE, 0)
        self.port.closePort()


# ── ROS 노드 ─────────────────────────────────────────────────────────────────

class WaiterNode(Node):
    def __init__(self):
        super().__init__('waiter')

        self.declare_parameter('config_path',    _DEFAULT_CONFIG_PATH)
        self.declare_parameter('top_cam_path',   '')   # 빈 문자열 = YAML 값 사용
        self.declare_parameter('wrist_cam_path', '')
        self.declare_parameter('vlm_host',       '')   # 빈 문자열 = YAML 값 사용

        config_path = self.get_parameter('config_path').value
        self.get_logger().info(f'Loading config: {config_path}')

        cfg = _load_config(config_path)
        cfg['_config_path'] = config_path   # act_worker 전달용
        self._cfg = cfg

        self.get_logger().info(
            f"Starting ACT worker: model={cfg['model']['path']} "
            f"chunk_size={cfg['memory']['chunk_size']}"
        )
        self._model = ModelProcess(cfg)
        self.get_logger().info('ACT model worker ready.')

        cb = ReentrantCallbackGroup()
        self._pickup_server = ActionServer(
            self, Pickup, 'pickup', self._execute_pickup,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb,
        )
        self._serve_server = ActionServer(
            self, Serve, 'serve', self._execute_serve,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb,
        )
        self.get_logger().info('WaiterNode ready  (ACT / Pickup + Serve)')

    def destroy_node(self):
        self._model.close()
        super().destroy_node()

    def _resolve_cam(self, goal_value: str, yaml_key: str, ros_param: str) -> str:
        """goal → ROS param → YAML 순서로 카메라 경로 결정."""
        if goal_value:
            return goal_value
        ros_val = self.get_parameter(ros_param).value
        if ros_val:
            return ros_val
        return self._cfg['cameras'][yaml_key]

    # ── Pickup ────────────────────────────────────────────────────────────────

    def _execute_pickup(self, goal_handle):
        goal = goal_handle.request
        top_cam   = self._resolve_cam(getattr(goal, 'top_cam_path',   ''), 'top_path',   'top_cam_path')
        wrist_cam = self._resolve_cam(getattr(goal, 'wrist_cam_path', ''), 'wrist_path', 'wrist_cam_path')

        self.get_logger().info(
            f'Pickup started — top={top_cam} wrist={wrist_cam}'
        )
        feedback = Pickup.Feedback()
        feedback.status = 'Pickup in progress'
        goal_handle.publish_feedback(feedback)

        try:
            self._do_act_task(
                goal_handle=goal_handle,
                top_cam_path=top_cam,
                wrist_cam_path=wrist_cam,
                duration_s=self._cfg['task']['pickup_duration_s'],
                feedback=feedback,
                vlm_prompt=self._cfg['vlm'].get('pickup_prompt', ''),
            )
        except _TaskComplete:
            pass
        except Exception as e:
            goal_handle.abort()
            result = Pickup.Result()
            result.success = False
            result.message = str(e)
            self.get_logger().error(f'Pickup aborted: {e}')
            return result

        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
            result = Pickup.Result()
            result.success = False
            result.message = 'Pickup canceled.'
        else:
            goal_handle.succeed()
            result = Pickup.Result()
            result.success = True
            result.message = 'Pickup complete.'

        self.get_logger().info(result.message)
        return result

    # ── Serve ─────────────────────────────────────────────────────────────────

    def _execute_serve(self, goal_handle):
        goal = goal_handle.request
        top_cam   = self._resolve_cam(getattr(goal, 'top_cam_path',   ''), 'top_path',   'top_cam_path')
        wrist_cam = self._resolve_cam(getattr(goal, 'wrist_cam_path', ''), 'wrist_path', 'wrist_cam_path')

        self.get_logger().info(
            f'Serve started — top={top_cam} wrist={wrist_cam}'
        )
        feedback = Serve.Feedback()
        feedback.status = 'Serve in progress'
        goal_handle.publish_feedback(feedback)

        try:
            self._do_act_task(
                goal_handle=goal_handle,
                top_cam_path=top_cam,
                wrist_cam_path=wrist_cam,
                duration_s=self._cfg['task']['serve_duration_s'],
                feedback=feedback,
                vlm_prompt=self._cfg['vlm'].get('serve_prompt', ''),
            )
        except _TaskComplete:
            goal_handle.succeed()
            result = Serve.Result()
            result.success = True
            result.message = 'Serve complete (home reached).'
            self.get_logger().info(result.message)
            return result
        except Exception as e:
            goal_handle.abort()
            result = Serve.Result()
            result.success = False
            result.message = str(e)
            self.get_logger().error(f'Serve aborted: {e}')
            return result

        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
            result = Serve.Result()
            result.success = False
            result.message = 'Serve canceled.'
        else:
            goal_handle.succeed()
            result = Serve.Result()
            result.success = True
            result.message = 'Serve complete (duration).'

        self.get_logger().info(result.message)
        return result

    # ── 공통 ACT 제어 루프 ────────────────────────────────────────────────────

    def _do_act_task(
        self,
        goal_handle,
        top_cam_path: str,
        wrist_cam_path: str,
        duration_s: float,
        feedback,
        vlm_prompt: str = '',
    ):
        """Pickup / Serve 공통 ACT 추론 + 실행 루프.

        홈 포지션 dwell_s 경과 시:
          - vlm.enabled=true 이고 vlm_prompt가 있으면 VLM으로 완료 판단
          - vlm.enabled=false 이면 홈 감지만으로 완료 판단
        """
        import collections, math

        cfg  = self._cfg
        ctrl = cfg['control']
        mem  = cfg['memory']
        cam  = cfg['cameras']
        home_cfg = cfg['home']

        control_hz     = float(ctrl['hz'])
        interp_mult    = int(ctrl['interpolation_mult'])
        ema_alpha      = float(ctrl['ema_alpha'])
        queue_thr      = int(ctrl['rtc_queue_threshold'])
        chunk_size     = int(mem['chunk_size'])
        action_dim     = int(mem['action_dim'])

        period     = 1.0 / control_hz
        sub_period = period / interp_mult

        home_ranges = {
            int(k): (float(v[0]), float(v[1]))
            for k, v in home_cfg['ranges'].items()
        }
        home_dwell_s = float(home_cfg['dwell_s'])

        robot     = _OMXRobot(cfg)
        init_pos  = robot.get_positions()
        top_cam   = _AsyncCamera(top_cam_path,   'top',   cam['width'], cam['height'], cam['fps'])
        wrist_cam = _AsyncCamera(wrist_cam_path, 'wrist', cam['width'], cam['height'], cam['fps'])

        step       = 0
        start_time = time.time()

        obs_lock    = threading.Lock()
        queue_lock  = threading.Lock()
        infer_stop  = threading.Event()
        infer_error = [None]

        latest_obs   = {'top': None, 'wrist': None, 'state': None}
        action_queue = collections.deque()

        infer_count   = [0]
        infer_skipped = [0]
        executed_count = [0]
        latency_history: list[float] = []

        def _p95() -> float | None:
            if not latency_history:
                return None
            return sorted(latency_history)[int(len(latency_history) * 0.95)]

        home_since    = None
        has_left_home = False
        task_complete = False

        # ── 인퍼런스 스레드 ───────────────────────────────────────────────────
        def _inference_loop():
            while not infer_stop.is_set():
                with queue_lock:
                    qsize      = len(action_queue)
                    idx_before = executed_count[0]

                if qsize > queue_thr:
                    infer_skipped[0] += 1
                    time.sleep(0.005)
                    continue

                with obs_lock:
                    obs = latest_obs.copy()

                if obs['top'] is None:
                    time.sleep(0.005)
                    continue

                try:
                    p95   = _p95()
                    delay = math.ceil(p95 / period) if p95 else 0
                    p95_ms = f'{p95*1000:.0f}ms' if p95 else 'N/A'

                    self.get_logger().info(
                        f'[infer-trigger #{infer_count[0]+1}] '
                        f'qsize={qsize} threshold={queue_thr} '
                        f'p95={p95_ms} delay_hint={delay} '
                        f'(skipped={infer_skipped[0]})'
                    )
                    infer_skipped[0] = 0

                    t_start = time.perf_counter()
                    _original, processed_chunk = self._model.get_action_chunk(
                        top_image=obs['top'],
                        wrist_image=obs['wrist'],
                        state=obs['state'],
                        inference_delay=delay,
                    )
                    infer_s = time.perf_counter() - t_start

                    if infer_count[0] > 0:   # warmup 제외
                        latency_history.append(infer_s)
                        if len(latency_history) > 50:
                            latency_history.pop(0)

                    real_delay  = round(infer_s / period)
                    consumed    = max(0, executed_count[0] - idx_before)
                    actual_delay = consumed if abs(consumed - real_delay) <= 1 else real_delay
                    actual_delay = max(0, min(actual_delay, len(processed_chunk)))

                    with queue_lock:
                        q_before = len(action_queue)
                        action_queue.clear()
                        queued = processed_chunk[actual_delay:]
                        action_queue.extend(queued)
                        q_after = len(action_queue)

                        grip_seq  = queued[:, 5] if len(queued) else np.array([], dtype=np.float32)
                        grip_head = ','.join(f'{v:.1f}' for v in grip_seq[:12])
                        grip_min  = float(np.min(grip_seq)) if len(grip_seq) else float('nan')
                        grip_max  = float(np.max(grip_seq)) if len(grip_seq) else float('nan')
                        cf = queued[0]  if len(queued) else np.zeros(action_dim)
                        cl = queued[-1] if len(queued) else np.zeros(action_dim)

                    infer_count[0] += 1
                    self.get_logger().info(
                        f'[infer-done #{infer_count[0]}] '
                        f'infer={infer_s*1000:.0f}ms p95={p95_ms} '
                        f'real_delay={real_delay} consumed={consumed} actual_delay={actual_delay} '
                        f'q_before={q_before}→q_after={q_after} '
                        f'chunk_first=[{",".join(f"{v:.2f}" for v in cf[:3])},...,grip={cf[5]:.2f}] '
                        f'chunk_last=[{",".join(f"{v:.2f}" for v in cl[:3])},...,grip={cl[5]:.2f}] '
                        f'grip_minmax={grip_min:.1f}/{grip_max:.1f} '
                        f'grip_head=[{grip_head}]'
                    )

                except Exception as e:
                    infer_error[0] = e
                    infer_stop.set()
                    return

        infer_thread = threading.Thread(target=_inference_loop, daemon=True)

        try:
            top_img   = top_cam.read_latest()
            wrist_img = wrist_cam.read_latest()
            state     = robot.get_positions()
            with obs_lock:
                latest_obs = {'top': top_img, 'wrist': wrist_img, 'state': state}

            infer_thread.start()

            deadline = time.time() + 60.0
            while time.time() < deadline:
                if goal_handle.is_cancel_requested:
                    return
                if infer_error[0]:
                    raise infer_error[0]
                with queue_lock:
                    if action_queue:
                        break
                time.sleep(0.05)
            else:
                raise RuntimeError('ACT inference did not produce actions within 60s')

            prev_action_interp = None
            ema_state          = None

            # ── 제어 루프 ────────────────────────────────────────────────────
            while not goal_handle.is_cancel_requested:
                t0 = time.time()

                if infer_error[0]:
                    raise infer_error[0]

                if duration_s > 0 and (time.time() - start_time) >= duration_s:
                    self.get_logger().info(f'Duration {duration_s}s reached.')
                    break

                top_img   = top_cam.read_latest()
                wrist_img = wrist_cam.read_latest()
                state     = robot.get_positions()
                with obs_lock:
                    latest_obs = {'top': top_img, 'wrist': wrist_img, 'state': state}

                # ── 홈 포지션 감지 + VLM 완료 판단 ──────────────────────────
                in_home = all(lo <= state[i] <= hi for i, (lo, hi) in home_ranges.items())
                if not in_home:
                    if not has_left_home:
                        has_left_home = True
                        self.get_logger().info('Left initial position. Home detection active.')
                    if home_since is not None:
                        self.get_logger().info('Left home position.')
                    home_since = None
                else:
                    if not has_left_home:
                        pass   # 작업 시작 전 → 무시
                    elif home_since is None:
                        home_since = time.time()
                        self.get_logger().info('Home position entered.')
                    elif time.time() - home_since >= home_dwell_s:
                        vlm_cfg     = cfg.get('vlm', {})
                        vlm_enabled = bool(vlm_cfg.get('enabled', False))
                        use_vlm     = vlm_enabled and bool(vlm_prompt)

                        if use_vlm:
                            self.get_logger().info(
                                f'Home held for {home_dwell_s}s → asking VLM...'
                            )
                            feedback.status = 'Checking task completion via VLM...'
                            goal_handle.publish_feedback(feedback)

                            # ROS 파라미터로 host 오버라이드 가능
                            ros_vlm_host = self.get_parameter('vlm_host').value
                            effective_vlm_cfg = dict(vlm_cfg)
                            if ros_vlm_host:
                                effective_vlm_cfg['host'] = ros_vlm_host

                            try:
                                complete, vlm_answer = _vlm_check_task_complete(
                                    top_img, vlm_prompt, effective_vlm_cfg
                                )
                                self.get_logger().info(
                                    f'VLM answer: "{vlm_answer}" → complete={complete}'
                                )
                            except Exception as e:
                                self.get_logger().warn(
                                    f'VLM check failed: {e}. Continuing.'
                                )
                                complete = False

                            if complete:
                                self.get_logger().info('VLM confirmed task complete.')
                                task_complete = True
                                raise _TaskComplete()
                            else:
                                self.get_logger().info(
                                    'VLM says task not complete. Continuing.'
                                )
                                home_since = None   # dwell 재카운트
                        else:
                            # VLM 비활성화: 홈 포지션 감지만으로 완료
                            self.get_logger().info(
                                f'Home held for {home_dwell_s}s → task complete '
                                f'(VLM disabled or no prompt).'
                            )
                            task_complete = True
                            raise _TaskComplete()

                with queue_lock:
                    qsize  = len(action_queue)
                    action = action_queue.popleft() if action_queue else None
                    if action is not None:
                        executed_count[0] += 1

                if action is not None:
                    step += 1
                    feedback.status = f'step {step}'
                    goal_handle.publish_feedback(feedback)

                    self.get_logger().info(
                        f'[ctrl-step {step:04d}] q={qsize} '
                        f'action=[{",".join(f"{v:.2f}" for v in action[:3])},...,grip={action[5]:.2f}] '
                        f'state=[{",".join(f"{v:.2f}" for v in state[:3])},...,grip={state[5]:.2f}] '
                        f'diff=[{",".join(f"{v:.2f}" for v in (action-state)[:3])},...,grip_diff={action[5]-state[5]:.2f}]'
                    )

                    # gripper만 EMA (arm 관절은 raw → chunk 경계 stop-start 방지)
                    if ema_state is None:
                        ema_state = action.copy()
                    else:
                        ema_state[5] = ema_alpha * action[5] + (1.0 - ema_alpha) * ema_state[5]
                    action[5] = ema_state[5]

                    src = prev_action_interp if prev_action_interp is not None else action
                    for i in range(1, interp_mult + 1):
                        if goal_handle.is_cancel_requested:
                            break
                        t_interp = i / interp_mult
                        robot.set_positions(src * (1.0 - t_interp) + action * t_interp)
                        time.sleep(sub_period)

                    prev_action_interp = action.copy()

                else:
                    self.get_logger().warn(
                        f'[ctrl-step {step:04d}] q={qsize} EMPTY — holding position'
                    )
                    elapsed = time.time() - t0
                    if elapsed < period:
                        time.sleep(period - elapsed)

        finally:
            infer_stop.set()
            infer_thread.join(timeout=5.0)
            top_cam.close()
            wrist_cam.close()
            if goal_handle.is_cancel_requested or task_complete:
                reason = 'Task complete' if task_complete else 'Canceled'
                self.get_logger().info(f'{reason} — returning to initial position...')
                try:
                    robot.return_to_position(init_pos, duration_s=3.0)
                except Exception as e:
                    self.get_logger().warn(f'Return failed: {e}')
            robot.close()
            self.get_logger().info('Hardware disconnected.')


# ── 엔트리포인트 ──────────────────────────────────────────────────────────────

def main(args=None):
    rp.init(args=args)
    node = WaiterNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rp.shutdown()


if __name__ == '__main__':
    main()
