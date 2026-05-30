"""
SmolVLA serving orchestration layer (RTC).

SmolVLA 정책 서버 접근, 카메라 캡처, Dynamixel 제어,
VLM 완료 확인, RTC 제어 루프를 담당한다.
act_serving_orchestrator.py와 동일한 작동 흐름을 유지하되
SmolVLA RTC 추론 방식(prev_chunk_left_over, execution_horizon)을 사용한다.
"""

import base64
import collections
from dataclasses import dataclass
import math
from multiprocessing.shared_memory import SharedMemory
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import requests
import yaml

from single_arm_controller_interfaces.srv import SmolVLAPolicyInference, SetTask

_MARKER_SIZE = 100
_MARKER_X = 640 - _MARKER_SIZE - 10
_MARKER_Y = 10
_COLOR_BLUE = (0, 0, 255)
_COLOR_RED  = (255, 0, 0)

_DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / 'config' / 'smolvla_serving_config.yaml')

FeedbackCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class TaskOutcome:
    status: str
    message: str

    @property
    def success(self) -> bool:
        return self.status == 'success'

    @property
    def canceled(self) -> bool:
        return self.status == 'canceled'


class TaskCompleted(Exception):
    pass


def _add_marker(image_rgb: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    img = image_rgb.copy()
    cv2.rectangle(
        img,
        (_MARKER_X, _MARKER_Y),
        (_MARKER_X + _MARKER_SIZE, _MARKER_Y + _MARKER_SIZE),
        color, -1,
    )
    return img


def check_task_completion_with_vlm(
    image_rgb: np.ndarray,
    prompt: str,
    vlm_config: dict,
) -> tuple[bool, str]:
    _, buf = cv2.imencode('.jpg', cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
    img_b64 = base64.b64encode(buf.tobytes()).decode('utf-8')

    resp = requests.post(
        f"{vlm_config['host']}/api/chat",
        json={
            'model':    vlm_config['model'],
            'messages': [{'role': 'user', 'content': prompt, 'images': [img_b64]}],
            'stream':   False,
            'options':  {'temperature': 0},
        },
        timeout=float(vlm_config['timeout_s']),
    )
    resp.raise_for_status()
    answer = resp.json()['message']['content'].strip()
    complete = answer.lower().startswith('false')
    return complete, answer


def load_smolvla_serving_config(path: str) -> dict:
    with open(path, 'r') as f:
        config = yaml.safe_load(f)

    memory_config = config['memory']
    top_image_shape = tuple(memory_config['top_shape'])
    wrist_image_shape = tuple(memory_config['wrist_shape'])
    state_dimension = memory_config['state_dim']
    action_chunk_size = memory_config['chunk_size']
    action_dimension = memory_config['action_dim']
    execution_horizon = int(memory_config.get('execution_horizon', 15))

    memory_config['_top_bytes'] = int(np.prod(top_image_shape))
    memory_config['_wrist_bytes'] = int(np.prod(wrist_image_shape))
    memory_config['_state_bytes'] = state_dimension * 4
    memory_config['_obs_bytes'] = (
        memory_config['_top_bytes']
        + memory_config['_wrist_bytes']
        + memory_config['_state_bytes']
    )
    memory_config['_act_planes'] = 2
    memory_config['_act_bytes'] = 2 * action_chunk_size * action_dimension * 4
    memory_config['_prev_bytes'] = execution_horizon * action_dimension * 4

    return config


def _normalize_prev_chunk(
    prev_raw: np.ndarray,
    target_len: int,
    action_dim: int,
    ema_alpha: float,
) -> np.ndarray:
    """
    이전 청크의 unexecuted tail을 execution_horizon 길이로 정규화한다.
    grip 차원(index 5)에는 EMA를 적용해 oscillation을 억제한다.
    """
    n = len(prev_raw)
    if n >= target_len:
        normalized = prev_raw[:target_len].copy()
    else:
        pad = np.zeros((target_len - n, action_dim), dtype=np.float32)
        normalized = np.concatenate([prev_raw, pad], axis=0)

    # grip(index 5) EMA 적용
    grip_ema = float(normalized[0, 5])
    for i in range(len(normalized)):
        grip_ema = ema_alpha * float(normalized[i, 5]) + (1.0 - ema_alpha) * grip_ema
        normalized[i, 5] = grip_ema

    return normalized


class SmolVLAPolicyServerClient:
    """
    별도 ROS 노드로 실행 중인 SmolVLA policy server에 접속한다.
    대용량 관찰/액션 배열은 shared memory로 교환하고,
    prev_chunk_left_over도 shared memory로 전달한다.
    ROS service는 트리거/완료 신호만 담당한다.
    """

    def __init__(self, node, config: dict):
        memory_config = config['memory']
        ipc_config = config.get('ipc', {})

        top_image_shape = tuple(memory_config['top_shape'])
        wrist_image_shape = tuple(memory_config['wrist_shape'])
        state_dimension = memory_config['state_dim']
        action_chunk_size = memory_config['chunk_size']
        action_dimension = memory_config['action_dim']
        execution_horizon = int(memory_config.get('execution_horizon', 15))

        observation_bytes = memory_config['_obs_bytes']
        action_bytes = memory_config['_act_bytes']
        action_planes = memory_config['_act_planes']
        prev_bytes = memory_config['_prev_bytes']

        self._node = node
        self._logger = node.get_logger()
        self._lock = threading.Lock()
        self._service_name = ipc_config.get('service_name', '/smolvla_policy/infer')
        self._connect_timeout_s = float(ipc_config.get('connect_timeout_s', 120.0))

        self._client = node.create_client(SmolVLAPolicyInference, self._service_name)
        if not self._client.wait_for_service(timeout_sec=self._connect_timeout_s):
            raise RuntimeError(f'SmolVLA policy service not available: {self._service_name}')

        set_task_name = ipc_config.get('set_task_service_name', '/smolvla_policy/set_task')
        self._set_task_client = node.create_client(SetTask, set_task_name)
        if not self._set_task_client.wait_for_service(timeout_sec=self._connect_timeout_s):
            raise RuntimeError(f'SetTask service not available: {set_task_name}')

        obs_name = ipc_config.get('shm_obs_name', 'smolvla_policy_observation')
        act_name = ipc_config.get('shm_act_name', 'smolvla_policy_action')
        prev_name = ipc_config.get('shm_prev_name', 'smolvla_policy_prev_chunk')

        self._shm_obs = self._attach_shared_memory(obs_name, observation_bytes)
        self._shm_act = self._attach_shared_memory(act_name, action_bytes)
        self._shm_prev = self._attach_shared_memory(prev_name, prev_bytes)

        top_image_bytes = memory_config['_top_bytes']
        wrist_image_bytes = memory_config['_wrist_bytes']

        self._top_image_buffer = np.ndarray(
            top_image_shape, dtype=np.uint8, buffer=self._shm_obs.buf, offset=0
        )
        self._wrist_image_buffer = np.ndarray(
            wrist_image_shape,
            dtype=np.uint8,
            buffer=self._shm_obs.buf,
            offset=top_image_bytes,
        )
        self._joint_state_buffer = np.ndarray(
            state_dimension,
            dtype=np.float32,
            buffer=self._shm_obs.buf,
            offset=top_image_bytes + wrist_image_bytes,
        )
        self._action_buffer = np.ndarray(
            (action_planes, action_chunk_size, action_dimension),
            dtype=np.float32,
            buffer=self._shm_act.buf,
        )
        self._prev_chunk_buffer = np.ndarray(
            (execution_horizon, action_dimension),
            dtype=np.float32,
            buffer=self._shm_prev.buf,
        )
        self._logger.info(f'Connected to SmolVLA policy server: {self._service_name}')

    def _attach_shared_memory(self, name: str, expected_size: int) -> SharedMemory:
        deadline = time.time() + self._connect_timeout_s
        last_error = None
        while time.time() < deadline:
            try:
                shm = SharedMemory(name=name)
                if shm.size < expected_size:
                    shm.close()
                    raise RuntimeError(
                        f'shared memory {name} too small: {shm.size} < {expected_size}'
                    )
                return shm
            except FileNotFoundError as e:
                last_error = e
                time.sleep(0.1)
        raise RuntimeError(f'Cannot attach shared memory {name}: {last_error}')

    def get_action_chunk(
        self,
        top_image: np.ndarray,
        wrist_image: np.ndarray,
        state: np.ndarray,
        task: str = '',
        inference_delay: int = 0,
        prev_chunk_left_over: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        추론 실행.
        shared memory에 observation과 prev_chunk를 쓰고 service로 trigger한다.
        Returns: (original_chunk, processed_chunk) — 둘 다 (chunk_size, action_dim)
        """
        with self._lock:
            np.copyto(self._top_image_buffer, top_image)
            np.copyto(self._wrist_image_buffer, wrist_image)
            np.copyto(self._joint_state_buffer, state)

            has_prev = prev_chunk_left_over is not None
            if has_prev:
                np.copyto(self._prev_chunk_buffer, prev_chunk_left_over)

            request = SmolVLAPolicyInference.Request()
            request.inference_delay = int(inference_delay)
            request.has_prev_chunk = has_prev
            request.task = task

            future = self._client.call_async(request)
            done = threading.Event()
            future.add_done_callback(lambda _: done.set())
            if not done.wait(timeout=self._connect_timeout_s):
                raise TimeoutError(f'SmolVLA policy inference timeout: {self._service_name}')

            response = future.result()
            if response is None:
                raise RuntimeError('SmolVLA policy inference service returned no response')
            if not response.success:
                raise RuntimeError(response.message)

            return self._action_buffer[0].copy(), self._action_buffer[1].copy()

    def switch_to_task(self, task: str):
        req = SetTask.Request()
        req.task = task
        future = self._set_task_client.call_async(req)
        done = threading.Event()

        def _on_done(f):
            try:
                resp = f.result()
                if resp.success:
                    self._logger.info(f'Model switched: {resp.message}')
                else:
                    self._logger.error(f'Model switch failed: {resp.message}')
            except Exception as e:
                self._logger.error(f'Model switch error: {e}')
            done.set()

        future.add_done_callback(_on_done)
        return done

    def close(self):
        self._shm_obs.close()
        self._shm_act.close()
        self._shm_prev.close()


class ThreadedCamera:
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


def make_dynamixel_position_converters(dxl_max: int):
    def raw_to_norm(raw):
        return (raw / dxl_max) * 200.0 - 100.0

    def norm_to_raw(norm):
        return int(((min(100.0, max(-100.0, norm)) + 100.0) / 200.0) * dxl_max)

    def raw_to_grip(raw):
        return (raw / dxl_max) * 100.0

    def grip_to_raw(norm):
        return int((min(100.0, max(0.0, norm)) / 100.0) * dxl_max)

    return raw_to_norm, norm_to_raw, raw_to_grip, grip_to_raw


class DynamixelArm:
    _ADDR_TORQUE      = 64
    _ADDR_GOAL_POS    = 116
    _ADDR_PRESENT_POS = 132
    _LEN_POS          = 4

    def __init__(self, config: dict):
        robot_config = config['robot']
        self._motor_ids = robot_config['motor_ids']
        (self._raw_to_norm, self._norm_to_raw,
         self._raw_to_grip, self._grip_to_raw) = make_dynamixel_position_converters(
            robot_config['dxl_max']
        )

        from dynamixel_sdk import (
            PortHandler, PacketHandler,
            GroupSyncRead, GroupSyncWrite, COMM_SUCCESS,
        )
        self._OK = COMM_SUCCESS
        self.port = PortHandler(robot_config['port'])
        self.pkt = PacketHandler(float(robot_config['protocol']))
        if not self.port.openPort():
            raise RuntimeError(f"Cannot open {robot_config['port']}")
        if not self.port.setBaudRate(robot_config['baud']):
            raise RuntimeError(f"Cannot set baud {robot_config['baud']}")
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
        steps = max(int(duration_s * fps), 1)
        period = 1.0 / fps
        for step in range(1, steps + 1):
            t = step / steps
            self.set_positions(current * (1 - t) + target * t)
            time.sleep(period)

    def close(self):
        for mid in self._motor_ids:
            self.pkt.write1ByteTxRx(self.port, mid, self._ADDR_TORQUE, 0)
        self.port.closePort()


class SmolVLAServingOrchestrator:
    """Pickup/Serve 작업 수행 로직. SmolVLA RTC 추론을 사용한다."""

    def __init__(self, config_path: str, node, vlm_host: str = ''):
        self._node = node
        self._logger = node.get_logger()
        self._vlm_host = vlm_host

        self._logger.info(f'Loading config: {config_path}')
        config = load_smolvla_serving_config(config_path)
        config['_config_path'] = config_path
        self._config = config

        self._logger.info(
            f"Connecting SmolVLA policy server: service="
            f"{config.get('ipc', {}).get('service_name', '/smolvla_policy/infer')} "
            f"chunk_size={config['memory']['chunk_size']}"
        )
        self._model = SmolVLAPolicyServerClient(node, config)
        self._logger.info('SmolVLA policy server client ready.')

    @property
    def config(self) -> dict:
        return self._config

    def close(self):
        self._model.close()

    def resolve_camera_path(self, goal_value: str, yaml_key: str, ros_override: str) -> str:
        if goal_value:
            return goal_value
        if ros_override:
            return ros_override
        return self._config['cameras'][yaml_key]

    def run_pickup(
        self,
        top_cam_path: str,
        wrist_cam_path: str,
        feedback_cb: FeedbackCallback,
        cancel_cb: CancelCallback,
    ) -> TaskOutcome:
        vlm_completed = False
        task_config = self._config.get('tasks', {})
        task_text = task_config.get('pickup_task_text', 'pick up the object')
        try:
            self._run_smolvla_task(
                top_cam_path=top_cam_path,
                wrist_cam_path=wrist_cam_path,
                duration_s=self._config['task']['pickup_duration_s'],
                feedback_cb=feedback_cb,
                cancel_cb=cancel_cb,
                vlm_prompt=self._config['vlm'].get('pickup_prompt', ''),
                task_name='pickup',
                task_text=task_text,
            )
        except TaskCompleted:
            vlm_completed = True

        if vlm_completed:
            self._logger.info('Pickup VLM complete -> switching to serve model')
            threading.Thread(
                target=self._model.switch_to_task, args=('serve',), daemon=True
            ).start()

        if cancel_cb():
            return TaskOutcome('canceled', 'Pickup canceled.')
        return TaskOutcome('success', 'Pickup complete.')

    def run_serve(
        self,
        top_cam_path: str,
        wrist_cam_path: str,
        has_drink: bool,
        direction: str,
        feedback_cb: FeedbackCallback,
        cancel_cb: CancelCallback,
    ) -> TaskOutcome:
        if not has_drink:
            marker_color = _COLOR_BLUE
        else:
            marker_color = _COLOR_BLUE if direction == 'left' else _COLOR_RED

        self._logger.info(
            f'Running serve task. has_drink={has_drink} direction={direction} '
            f'marker={"BLUE" if marker_color == _COLOR_BLUE else "RED"}'
        )

        task_config = self._config.get('tasks', {})
        if not has_drink:
            task_text = task_config.get('serve_no_drink_task_text', 'serve without drink')
        elif direction == 'left':
            task_text = task_config.get('serve_left_task_text', 'serve drink to the left')
        else:
            task_text = task_config.get('serve_right_task_text', 'serve drink to the right')

        vlm_completed = False
        try:
            self._run_smolvla_task(
                top_cam_path=top_cam_path,
                wrist_cam_path=wrist_cam_path,
                duration_s=self._config['task']['serve_duration_s'],
                feedback_cb=feedback_cb,
                cancel_cb=cancel_cb,
                vlm_prompt=self._config['vlm'].get('serve_prompt', ''),
                task_name='serve',
                task_text=task_text,
                marker_color=marker_color,
            )
        except TaskCompleted:
            vlm_completed = True

        if vlm_completed:
            self._logger.info('Serve VLM complete -> switching to pickup model')
            threading.Thread(
                target=self._model.switch_to_task, args=('pickup',), daemon=True
            ).start()
            return TaskOutcome('success', 'Serve complete (home reached).')

        if cancel_cb():
            return TaskOutcome('canceled', 'Serve canceled.')
        return TaskOutcome('success', 'Serve complete (duration).')

    def _run_smolvla_task(
        self,
        top_cam_path: str,
        wrist_cam_path: str,
        duration_s: float,
        feedback_cb: FeedbackCallback,
        cancel_cb: CancelCallback,
        vlm_prompt: str = '',
        task_name: str = 'pickup',
        task_text: str = '',
        marker_color: tuple[int, int, int] | None = None,
    ):
        """Pickup / Serve 공통 SmolVLA RTC 추론 + 실행 루프."""
        config = self._config
        control_config = config['control']
        memory_config = config['memory']
        camera_config = config['cameras']
        home_config = config['home']

        control_hz = float(control_config['hz'])
        interpolation_steps = int(control_config['interpolation_mult'])
        ema_alpha = float(control_config['ema_alpha'])
        inference_queue_threshold = int(control_config['inference_queue_refill_threshold'])
        action_dimension = int(memory_config['action_dim'])
        execution_horizon = int(memory_config.get('execution_horizon', 15))

        period = 1.0 / control_hz
        sub_period = period / interpolation_steps

        home_ranges = {
            int(k): (float(v[0]), float(v[1]))
            for k, v in home_config['ranges'].items()
        }
        home_dwell_s = float(home_config['dwell_s'])
        return_duration_s = float(home_config.get('return_duration_s', 3.0))

        robot = DynamixelArm(config)
        initial_position = robot.get_positions()
        top_cam = ThreadedCamera(
            top_cam_path, 'top',
            camera_config['width'], camera_config['height'], camera_config['fps']
        )
        wrist_cam = ThreadedCamera(
            wrist_cam_path, 'wrist',
            camera_config['width'], camera_config['height'], camera_config['fps']
        )

        step = 0
        start_time = time.time()

        obs_lock = threading.Lock()
        queue_lock = threading.Lock()
        infer_stop = threading.Event()
        infer_error = [None]

        latest_obs = {'top': None, 'wrist': None, 'state': None}
        action_queue = collections.deque()

        # RTC 상태
        prev_original_chunk: np.ndarray | None = None  # 직전 청크의 원본(정규화된) 배열
        prev_lock = threading.Lock()

        infer_count = [0]
        infer_skipped = [0]
        executed_count = [0]
        latency_history: list[float] = []

        def get_p95_latency() -> float | None:
            if not latency_history:
                return None
            return sorted(latency_history)[int(len(latency_history) * 0.95)]

        home_since = None
        has_left_home = False
        task_complete = False

        def run_inference_loop():
            nonlocal prev_original_chunk

            while not infer_stop.is_set():
                with queue_lock:
                    qsize = len(action_queue)
                    idx_before = executed_count[0]

                if qsize > inference_queue_threshold:
                    infer_skipped[0] += 1
                    time.sleep(0.005)
                    continue

                with obs_lock:
                    obs = latest_obs.copy()

                if obs['top'] is None:
                    time.sleep(0.005)
                    continue

                try:
                    p95 = get_p95_latency()
                    delay = math.ceil(p95 / period) if p95 else 0
                    p95_ms = f'{p95*1000:.0f}ms' if p95 else 'N/A'

                    # prev_chunk_left_over 준비 (RTC)
                    with prev_lock:
                        prev_raw = prev_original_chunk

                    prev_left_over_norm = None
                    prev_raw_len = 0
                    prev_norm_len = 0

                    if prev_raw is not None:
                        # 아직 소비되지 않은 tail 계산
                        consumed_so_far = max(0, executed_count[0] - idx_before)
                        tail_start = min(delay + consumed_so_far, len(prev_raw))
                        tail = prev_raw[tail_start:]
                        prev_raw_len = len(tail)
                        prev_left_over_norm = _normalize_prev_chunk(
                            tail, execution_horizon, action_dimension, ema_alpha
                        )
                        prev_norm_len = len(prev_left_over_norm)

                    self._logger.info(
                        f'[infer-trigger #{infer_count[0]+1}] '
                        f'qsize={qsize} threshold={inference_queue_threshold} '
                        f'p95={p95_ms} delay_hint={delay} '
                        f'prev_raw_len={prev_raw_len} prev_normalized_len={prev_norm_len} '
                        f'(skipped={infer_skipped[0]})'
                    )
                    infer_skipped[0] = 0

                    t_start = time.perf_counter()
                    original_chunk, processed_chunk = self._model.get_action_chunk(
                        top_image=obs['top'],
                        wrist_image=obs['wrist'],
                        state=obs['state'],
                        task=task_text,
                        inference_delay=delay,
                        prev_chunk_left_over=prev_left_over_norm,
                    )
                    infer_s = time.perf_counter() - t_start

                    # 첫 추론(warmup)은 latency 기록 제외 (warmup 오염 방지)
                    if infer_count[0] > 0:
                        latency_history.append(infer_s)
                        if len(latency_history) > 50:
                            latency_history.pop(0)

                    real_delay = round(infer_s / period)
                    consumed = max(0, executed_count[0] - idx_before)
                    actual_delay = consumed if abs(consumed - real_delay) <= 1 else real_delay
                    actual_delay = max(0, min(actual_delay, len(processed_chunk)))

                    with queue_lock:
                        q_before = len(action_queue)
                        action_queue.clear()
                        queued = processed_chunk[actual_delay:]
                        action_queue.extend(queued)
                        q_after = len(action_queue)

                        grip_seq = queued[:, 5] if len(queued) else np.array([], dtype=np.float32)
                        grip_head = ','.join(f'{v:.1f}' for v in grip_seq[:12])
                        grip_min = float(np.min(grip_seq)) if len(grip_seq) else float('nan')
                        grip_max = float(np.max(grip_seq)) if len(grip_seq) else float('nan')
                        cf = queued[0] if len(queued) else np.zeros(action_dimension)
                        cl = queued[-1] if len(queued) else np.zeros(action_dimension)

                    # 다음 추론을 위해 원본(정규화) 청크 보관
                    with prev_lock:
                        prev_original_chunk = original_chunk.copy()

                    infer_count[0] += 1
                    self._logger.info(
                        f'[infer-done #{infer_count[0]}] '
                        f'infer={infer_s*1000:.0f}ms p95={p95_ms} '
                        f'real_delay={real_delay} consumed={consumed} actual_delay={actual_delay} '
                        f'q_before={q_before}->q_after={q_after} '
                        f'chunk_first=[{",".join(f"{v:.2f}" for v in cf[:3])},...,grip={cf[5]:.2f}] '
                        f'chunk_last=[{",".join(f"{v:.2f}" for v in cl[:3])},...,grip={cl[5]:.2f}] '
                        f'grip_minmax={grip_min:.1f}/{grip_max:.1f} '
                        f'grip_head=[{grip_head}]'
                    )

                except Exception as e:
                    infer_error[0] = e
                    infer_stop.set()
                    return

        infer_thread = threading.Thread(target=run_inference_loop, daemon=True)

        try:
            top_img = top_cam.read_latest()
            wrist_img = wrist_cam.read_latest()
            state = robot.get_positions()
            top_obs = _add_marker(top_img, marker_color) if marker_color else top_img
            with obs_lock:
                latest_obs = {'top': top_obs, 'wrist': wrist_img, 'state': state}

            infer_thread.start()

            deadline = time.time() + 60.0
            while time.time() < deadline:
                if cancel_cb():
                    return
                if infer_error[0]:
                    raise infer_error[0]
                with queue_lock:
                    if action_queue:
                        break
                time.sleep(0.05)
            else:
                raise RuntimeError('SmolVLA inference did not produce actions within 60s')

            # 첫 액션 위치로 2초에 걸쳐 부드럽게 이동
            with queue_lock:
                first_target = action_queue[0].copy()
            self._logger.info('Smooth start: moving to first action position over 2s')
            feedback_cb('Smooth start...')
            robot.return_to_position(first_target, duration_s=2.0)
            with queue_lock:
                action_queue.clear()

            prev_action_interp = None
            ema_state = None

            while not cancel_cb():
                t0 = time.time()

                if infer_error[0]:
                    raise infer_error[0]

                if duration_s > 0 and (time.time() - start_time) >= duration_s:
                    self._logger.info(f'Duration {duration_s}s reached.')
                    break

                top_img = top_cam.read_latest()
                wrist_img = wrist_cam.read_latest()
                state = robot.get_positions()
                top_obs = _add_marker(top_img, marker_color) if marker_color else top_img
                with obs_lock:
                    latest_obs = {'top': top_obs, 'wrist': wrist_img, 'state': state}

                in_home = all(lo <= state[i] <= hi for i, (lo, hi) in home_ranges.items())
                if not in_home:
                    if not has_left_home:
                        has_left_home = True
                        self._logger.info('Left initial position. Home detection active.')
                    if home_since is not None:
                        self._logger.info('Left home position.')
                    home_since = None
                else:
                    if not has_left_home:
                        pass
                    elif home_since is None:
                        home_since = time.time()
                        self._logger.info('Home position entered.')
                    elif time.time() - home_since >= home_dwell_s:
                        if time.time() - start_time < 5.0:
                            self._logger.info(
                                'Home reached but (now - infer_start) < 5s. Skipping VLM check.'
                            )
                            home_since = None
                            continue
                        vlm_config = config.get('vlm', {})
                        vlm_enabled = bool(vlm_config.get('enabled', False))
                        use_vlm = vlm_enabled and bool(vlm_prompt)

                        if use_vlm:
                            self._logger.info(
                                f'Home held for {home_dwell_s}s -> asking VLM...'
                            )
                            feedback_cb('Checking task completion via VLM...')

                            effective_vlm_config = dict(vlm_config)
                            if self._vlm_host:
                                effective_vlm_config['host'] = self._vlm_host

                            try:
                                complete, vlm_answer = check_task_completion_with_vlm(
                                    top_img, vlm_prompt, effective_vlm_config
                                )
                                self._logger.info(
                                    f'VLM answer: "{vlm_answer}" -> complete={complete}'
                                )
                                feedback_cb(
                                    f'VLM: "{vlm_answer}" -> {"complete" if complete else "not complete"}'
                                )
                            except Exception as e:
                                self._logger.warn(f'VLM check failed: {e}. Continuing.')
                                feedback_cb(f'VLM check failed: {e}')
                                complete = False

                            if complete:
                                self._logger.info('VLM confirmed task complete.')
                                task_complete = True
                                raise TaskCompleted()
                            else:
                                self._logger.info('VLM says task not complete. Continuing.')
                                home_since = None
                        else:
                            self._logger.info(
                                f'Home held for {home_dwell_s}s -> task complete '
                                f'(VLM disabled or no prompt).'
                            )
                            task_complete = True
                            raise TaskCompleted()

                with queue_lock:
                    qsize = len(action_queue)
                    action = action_queue.popleft() if action_queue else None
                    if action is not None:
                        executed_count[0] += 1

                if action is not None:
                    step += 1
                    feedback_cb(f'step {step}')

                    self._logger.info(
                        f'[ctrl-step {step:04d}] q={qsize} '
                        f'action=[{",".join(f"{v:.2f}" for v in action[:3])},...,grip={action[5]:.2f}] '
                        f'state=[{",".join(f"{v:.2f}" for v in state[:3])},...,grip={state[5]:.2f}] '
                        f'diff=[{",".join(f"{v:.2f}" for v in (action-state)[:3])},...,'
                        f'grip_diff={action[5]-state[5]:.2f}]'
                    )

                    # EMA: gripper(index 5)만 적용, arm 관절은 미적용 (stop-start 방지)
                    if ema_state is None:
                        ema_state = action.copy()
                    else:
                        ema_state[5] = ema_alpha * action[5] + (1.0 - ema_alpha) * ema_state[5]
                    action[5] = ema_state[5]

                    src = prev_action_interp if prev_action_interp is not None else action
                    for i in range(1, interpolation_steps + 1):
                        if cancel_cb():
                            break
                        t_interp = i / interpolation_steps
                        robot.set_positions(src * (1.0 - t_interp) + action * t_interp)
                        time.sleep(sub_period)

                    prev_action_interp = action.copy()

                else:
                    self._logger.warn(
                        f'[ctrl-step {step:04d}] q={qsize} EMPTY - holding position'
                    )
                    elapsed = time.time() - t0
                    if elapsed < period:
                        time.sleep(period - elapsed)

        finally:
            infer_stop.set()
            infer_thread.join(timeout=5.0)
            top_cam.close()
            wrist_cam.close()
            reason = (
                'Task complete' if task_complete
                else ('Canceled' if cancel_cb() else 'Duration elapsed')
            )
            self._logger.info(
                f'{reason} - returning to initial position ({return_duration_s}s)...'
            )
            try:
                robot.return_to_position(initial_position, duration_s=return_duration_s)
            except Exception as e:
                self._logger.warn(f'Return failed: {e}')
            robot.close()
            self._logger.info('Hardware disconnected.')
