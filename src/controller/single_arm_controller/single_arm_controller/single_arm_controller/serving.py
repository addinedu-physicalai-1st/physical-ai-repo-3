import base64
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

import cv2
import numpy as np
import requests
import rclpy as rp
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from single_arm_controller_interfaces.action import Pickup, Serve

# ── 모델 설정 ───────────────────────────────────────────────────────────────
_MODEL_PATH  = '/home/jr/ws/lerobot/outputs/300000/pretrained_model'
_DEVICE      = 'cuda'
_ROBOT_TYPE  = 'omx_follower'
_LEROBOT_PY  = '/home/jr/ws/lerobot/.venv/bin/python'
_WORKER_SCRIPT = str(Path(__file__).parent / 'model_worker.py')

_TASK            = 'pick up cup and place at target zone'
_CONTROL_HZ      = 30.0
_RTC_EXECUTION_HORIZON = 11
_RTC_QUEUE_THRESHOLD = 22
_RTC_DELAY_OFFSET_STEPS = -3  # +1 step = 33ms more future action at 30Hz

# ── VLM 설정 ────────────────────────────────────────────────────────────────
_VLM_HOST        = 'http://localhost:11434'   # Ollama 서버 주소
_VLM_MODEL       = 'qwen3-vl:4b'
_VLM_TIMEOUT_S   = 30.0

# ── 홈 포지션 범위 (serving_b 데이터셋 분석 기반) ────────────────────────────
# 인덱스: 0=shoulder_pan, 1=shoulder_lift, 2=elbow_flex,
#         3=wrist_flex,   4=wrist_roll,    5=gripper
_HOME_RANGE = {
    1: (-75.0, -40.0),   # shoulder_lift  (홈: -64.8 / mid: -8.4)
    2: ( 44.0,  56.0),   # elbow_flex     (홈:  54.9 / mid: 14.0)
    4: (-18.0,  16.0),   # wrist_roll     (홈:  -1.4 / mid: 25.1)
}
_HOME_DWELL_S = 2.0   # 홈 포지션에 머무를 시간 (초)


class _TaskComplete(Exception):
    """VLM이 task 완료를 확인했을 때 제어 루프를 탈출하기 위한 sentinel."""


def _vlm_check_task_complete(image_rgb: np.ndarray, task: str, vlm_host: str = _VLM_HOST) -> bool:
    """top 카메라 이미지를 Ollama Qwen3-VL에 보내 task 완료 여부를 묻는다."""
    _, buf = cv2.imencode('.jpg', cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
    img_b64 = base64.b64encode(buf.tobytes()).decode('utf-8')

    prompt = (
        'In the image, is there a container in the yellow zone on the left side? '
        'Answer with only "true" or "false".'
    )

    resp = requests.post(
        f'{vlm_host}/api/chat',
        json={
            'model': _VLM_MODEL,
            'messages': [{'role': 'user', 'content': prompt, 'images': [img_b64]}],
            'stream': False,
            'options': {'temperature': 0},
        },
        timeout=_VLM_TIMEOUT_S,
    )
    resp.raise_for_status()
    answer = resp.json()['message']['content'].strip()
    result = answer.lower().startswith('false')
    return result, answer  # (bool, 원문 응답)

# shared memory 레이아웃 (model_worker.py와 반드시 일치)
_TOP_SHAPE    = (480, 640, 3)
_WRIST_SHAPE  = (480, 640, 3)
_STATE_DIM    = 6
_CHUNK_SIZE   = 50
_ACTION_DIM   = 6
_TOP_BYTES    = int(np.prod(_TOP_SHAPE))
_WRIST_BYTES  = int(np.prod(_WRIST_SHAPE))
_STATE_BYTES  = _STATE_DIM * 4
_OBS_BYTES    = _TOP_BYTES + _WRIST_BYTES + _STATE_BYTES
_ACT_PLANES   = 2  # 0=original policy actions, 1=postprocessed robot actions
_ACT_BYTES    = _ACT_PLANES * _CHUNK_SIZE * _ACTION_DIM * 4


# ── ModelProcess ─────────────────────────────────────────────────────────────

class ModelProcess:
    """
    shared memory + Unix socket 시그널링으로 모델 워커 프로세스와 통신.
    TCP/pickle 없이 이미지를 zero-copy로 전달해 네트워크 지연 제거.
    """

    def __init__(self, model_path=_MODEL_PATH, device=_DEVICE, robot_type=_ROBOT_TYPE):
        # shared memory 생성
        self._shm_obs = SharedMemory(create=True, size=_OBS_BYTES)
        self._shm_act = SharedMemory(create=True, size=_ACT_BYTES)

        # numpy view (serving.py 측)
        self._top_buf   = np.ndarray(_TOP_SHAPE,   dtype=np.uint8,   buffer=self._shm_obs.buf, offset=0)
        self._wrist_buf = np.ndarray(_WRIST_SHAPE, dtype=np.uint8,   buffer=self._shm_obs.buf, offset=_TOP_BYTES)
        self._state_buf = np.ndarray(_STATE_DIM,   dtype=np.float32, buffer=self._shm_obs.buf, offset=_TOP_BYTES + _WRIST_BYTES)
        self._act_buf   = np.ndarray((_ACT_PLANES, _CHUNK_SIZE, _ACTION_DIM), dtype=np.float32, buffer=self._shm_act.buf)
        self._lock = threading.Lock()

        # Unix domain socket (시그널 전용)
        self._sock_path   = tempfile.mktemp(prefix='smolvla_', suffix='.sock')
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(self._sock_path)
        self._server_sock.listen(1)

        # 워커 프로세스 시작 (lerobot venv python)
        self._proc = subprocess.Popen([
            _LEROBOT_PY, _WORKER_SCRIPT,
            '--model-path',   model_path,
            '--device',       device,
            '--robot-type',   robot_type,
            '--socket-path',  self._sock_path,
            '--shm-obs-name', self._shm_obs.name,
            '--shm-act-name', self._shm_act.name,
            '--rtc-execution-horizon', str(_RTC_EXECUTION_HORIZON),
        ])

        # 모델 로딩 완료까지 대기 (최대 10분)
        self._server_sock.settimeout(600)
        self._conn, _ = self._server_sock.accept()
        assert self._recv_exact(1) == b'R', "Worker did not send READY"
        self._server_sock.settimeout(None)

    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self._conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Worker socket closed")
            buf.extend(chunk)
        return bytes(buf)

    def get_action_chunk(
        self,
        top_image: np.ndarray,
        wrist_image: np.ndarray,
        state: np.ndarray,
        task: str,
        robot_type: str = _ROBOT_TYPE,
        inference_delay: int = 0,
        prev_chunk_left_over: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            # shared memory에 관찰값 쓰기
            np.copyto(self._top_buf,   top_image)
            np.copyto(self._wrist_buf, wrist_image)
            np.copyto(self._state_buf, state)

            # GO 신호 + task + delay + prev original chunk
            task_bytes = task.encode('utf-8')
            msg = b'G'
            msg += struct.pack('>I', len(task_bytes)) + task_bytes
            msg += struct.pack('>I', inference_delay)
            if prev_chunk_left_over is not None:
                prev_bytes = prev_chunk_left_over.astype(np.float32).tobytes()
                msg += struct.pack('?', True)
                msg += struct.pack('>I', len(prev_bytes)) + prev_bytes
            else:
                msg += struct.pack('?', False)
            self._conn.sendall(msg)

            # DONE 신호 대기
            assert self._recv_exact(1) == b'D', "Worker did not send DONE"

            original = self._act_buf[0].copy()
            processed = self._act_buf[1].copy()
            return original, processed

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

# ── Hardware ───────────────────────────────────────────────────────────────
_ROBOT_PORT = '/dev/ttyACM0'
_ROBOT_BAUD = 1_000_000
_REALSENSE_SERIAL = '943222071539'
_WRIST_CAM_PATH = '/dev/video6'
_CAM_W, _CAM_H, _CAM_FPS = 640, 480, 30

# Dynamixel motor IDs: [shoulder_pan, shoulder_lift, elbow, wrist_flex, wrist_roll, gripper]
_MOTOR_IDS = [11, 12, 13, 14, 15, 16]
_PROTOCOL = 2.0
_ADDR_TORQUE = 64
_ADDR_GOAL_POS = 116
_ADDR_PRESENT_POS = 132
_LEN_POS = 4
_DXL_MAX = 4095


# ── Hardware helpers ───────────────────────────────────────────────────────

# 관절 (shoulder_pan ~ wrist_roll): RANGE_M100_100 → [-100, 100]
def _raw_to_norm(raw: int) -> float:
    return ((raw / _DXL_MAX) * 200.0) - 100.0

def _norm_to_raw(norm: float) -> int:
    clamped = min(100.0, max(-100.0, norm))
    return int(((clamped + 100.0) / 200.0) * _DXL_MAX)

# 그리퍼 (xl330-m288, id=16): RANGE_0_100 → [0, 100]
def _raw_to_gripper_norm(raw: int) -> float:
    return (raw / _DXL_MAX) * 100.0

def _gripper_norm_to_raw(norm: float) -> int:
    clamped = min(100.0, max(0.0, norm))
    return int((clamped / 100.0) * _DXL_MAX)


class _OMXRobot:
    def __init__(self):
        from dynamixel_sdk import (
            PortHandler, PacketHandler,
            GroupSyncRead, GroupSyncWrite, COMM_SUCCESS,
        )
        self._OK = COMM_SUCCESS
        self.port = PortHandler(_ROBOT_PORT)
        self.pkt = PacketHandler(_PROTOCOL)
        if not self.port.openPort():
            raise RuntimeError(f'Cannot open {_ROBOT_PORT}')
        if not self.port.setBaudRate(_ROBOT_BAUD):
            raise RuntimeError(f'Cannot set baud {_ROBOT_BAUD}')
        self.sync_read = GroupSyncRead(self.port, self.pkt, _ADDR_PRESENT_POS, _LEN_POS)
        self.sync_write = GroupSyncWrite(self.port, self.pkt, _ADDR_GOAL_POS, _LEN_POS)
        for mid in _MOTOR_IDS:
            self.sync_read.addParam(mid)
            self.pkt.write1ByteTxRx(self.port, mid, _ADDR_TORQUE, 1)

    def get_positions(self) -> np.ndarray:
        """현재 관절 위치 반환.
        관절(0~4): RANGE_M100_100 [-100, 100]
        그리퍼(5): RANGE_0_100  [0, 100]
        """
        self.sync_read.txRxPacket()
        values = []
        for i, mid in enumerate(_MOTOR_IDS):
            raw = self.sync_read.getData(mid, _ADDR_PRESENT_POS, _LEN_POS)
            if i == 5:  # gripper
                values.append(_raw_to_gripper_norm(raw))
            else:
                values.append(_raw_to_norm(raw))
        return np.array(values, dtype=np.float32)

    def set_positions(self, norm: np.ndarray):
        """관절 값을 모터로 전송.
        관절(0~4): RANGE_M100_100 [-100, 100]
        그리퍼(5): RANGE_0_100  [0, 100]
        """
        self.sync_write.clearParam()
        for i, (mid, n) in enumerate(zip(_MOTOR_IDS, norm)):
            if i == 5:  # gripper
                raw = _gripper_norm_to_raw(float(n))
            else:
                raw = _norm_to_raw(float(n))
            param = [(raw >> (8 * i) & 0xFF) for i in range(4)]
            self.sync_write.addParam(mid, param)
        self.sync_write.txPacket()

    def return_to_position(self, target: np.ndarray, duration_s: float = 3.0, fps: int = 50):
        """현재 위치에서 target(degrees)까지 선형 보간으로 천천히 이동."""
        current = self.get_positions()
        steps = max(int(duration_s * fps), 1)
        period = 1.0 / fps
        for step in range(1, steps + 1):
            t = step / steps
            interp = current * (1 - t) + target * t
            self.set_positions(interp)
            time.sleep(period)

    def close(self):
        for mid in _MOTOR_IDS:
            self.pkt.write1ByteTxRx(self.port, mid, _ADDR_TORQUE, 0)
        self.port.closePort()


class _WristCamera:
    def __init__(self, path: str = _WRIST_CAM_PATH):
        self.cap = cv2.VideoCapture(path)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, _CAM_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _CAM_H)
        self.cap.set(cv2.CAP_PROP_FPS, _CAM_FPS)
        if not self.cap.isOpened():
            raise RuntimeError(f'Cannot open wrist camera {path}')

    def read(self) -> np.ndarray:
        ret, frame = self.cap.read()
        if not ret:
            raise RuntimeError('Wrist camera read failed')
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def close(self):
        self.cap.release()


class _TopCamera:
    def __init__(self, serial: str = _REALSENSE_SERIAL):
        import pyrealsense2 as rs
        self.pipeline = rs.pipeline()
        cfg = rs.config()
        cfg.enable_device(serial)
        cfg.enable_stream(rs.stream.color, _CAM_W, _CAM_H, rs.format.rgb8, _CAM_FPS)
        self.pipeline.start(cfg)

    def read(self) -> np.ndarray:
        import pyrealsense2 as rs
        frames = self.pipeline.wait_for_frames()
        color = frames.get_color_frame()
        if not color:
            raise RuntimeError('RealSense frame missing')
        return np.asanyarray(color.get_data())

    def close(self):
        self.pipeline.stop()


# ── ROS node ───────────────────────────────────────────────────────────────

class SingleArmControllerNode(Node):
    def __init__(self):
        super().__init__('single_arm_controller')

        self.declare_parameter('wrist_cam_path',   _WRIST_CAM_PATH)
        self.declare_parameter('realsense_serial', _REALSENSE_SERIAL)
        self.declare_parameter('task',             _TASK)
        self.declare_parameter('vlm_host',         _VLM_HOST)

        # 노드 시작 시 모델 워커 프로세스 미리 실행 (request 올 때 바로 추론 가능)
        self.get_logger().info('Starting model worker process (loading model)...')
        self._model = ModelProcess()
        self.get_logger().info('Model worker ready.')

        cb = ReentrantCallbackGroup()
        self._pickup_action_server = ActionServer(
            self, Pickup, 'pickup', self._execute_pickup,
            callback_group=cb,
        )
        self._serve_action_server = ActionServer(
            self, Serve, 'serve', self._execute_serve,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb,
        )

        self.get_logger().info('SingleArmController node started.')

    def destroy_node(self):
        self._model.close()
        super().destroy_node()

    def _execute_pickup(self, goal_handle):
        self.get_logger().info('Pickup started.')

        feedback = Pickup.Feedback()
        feedback.status = 'Pickup in progress'
        goal_handle.publish_feedback(feedback)

        try:
            self._do_pickup(goal_handle)
            goal_handle.succeed()
            result = Pickup.Result()
            result.success = True
            result.message = 'Pickup completed.'
        except Exception as e:
            goal_handle.abort()
            result = Pickup.Result()
            result.success = False
            result.message = str(e)

        self.get_logger().info(f'Pickup finished: {result.message}')
        return result

    def _execute_serve(self, goal_handle):
        goal = goal_handle.request
        # goal > 파라미터 > 기본값 순으로 우선순위
        wrist_cam_path   = goal.wrist_cam_path   or self.get_parameter('wrist_cam_path').value
        realsense_serial = goal.realsense_serial or self.get_parameter('realsense_serial').value
        task             = goal.task             or self.get_parameter('task').value

        self.get_logger().info(
            f'Serve started — wrist_cam={wrist_cam_path} '
            f'realsense={realsense_serial} task="{task}"'
        )

        feedback = Serve.Feedback()
        feedback.status = 'Serve in progress'
        goal_handle.publish_feedback(feedback)

        try:
            self._do_serve(goal_handle, wrist_cam_path, realsense_serial, task)
        except _TaskComplete:
            goal_handle.succeed()
            result = Serve.Result()
            result.success = True
            result.message = 'Task completed (confirmed by VLM).'
            self.get_logger().info(result.message)
            return result
        except Exception as e:
            goal_handle.abort()
            result = Serve.Result()
            result.success = False
            result.message = str(e)
            self.get_logger().info(f'Serve aborted: {result.message}')
            return result

        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
            result = Serve.Result()
            result.success = False
            result.message = 'Serve canceled.'
            self.get_logger().info(result.message)
            return result

        goal_handle.succeed()
        result = Serve.Result()
        result.success = True
        result.message = 'Serve completed.'
        self.get_logger().info(f'Serve finished: {result.message}')
        return result

    def _do_pickup(self, goal_handle):
        self.get_logger().info('_do_pickup!')
        time.sleep(3)

    def _do_serve(self, goal_handle, wrist_cam_path: str, realsense_serial: str, task: str):
        self.get_logger().info('Starting serve with pre-loaded model.')

        robot = _OMXRobot()
        initial_pos = robot.get_positions()
        wrist_cam = _WristCamera(wrist_cam_path)
        top_cam = _TopCamera(realsense_serial)

        period = 1.0 / _CONTROL_HZ
        step = 0
        feedback = Serve.Feedback()
        home_since     = None
        task_complete  = False
        has_left_home  = False

        # 관절값 60초 기록
        _JOINT_LOG_SECS = 60.0
        _JOINT_LOG_PATH = '/tmp/joint_log.npy'
        joint_log = []
        joint_log_start = time.time()
        joint_log_saved = False

        # ── 비동기 인퍼런스 상태 (lerobot RTC 구조와 동일) ─────────────────
        import collections
        obs_lock    = threading.Lock()
        queue_lock  = threading.Lock()
        infer_stop  = threading.Event()
        infer_error = [None]

        latest_obs  = {'top': None, 'wrist': None, 'state': None}
        original_action_queue = collections.deque()    # RTC prev_chunk_left_over용 원본 action
        processed_action_queue = collections.deque()   # 로봇 실행용 postprocessed action

        import math
        _INFER_QUEUE_THRESHOLD   = _RTC_QUEUE_THRESHOLD
        _INTERPOLATION_MULT      = 5    # lerobot --interpolation_multiplier=5
        _SUB_PERIOD              = period / _INTERPOLATION_MULT  # ~6.67ms

        infer_count   = [0]
        infer_skipped = [0]
        executed_count = [0]

        # P95 latency tracker (lerobot과 동일)
        _latency_history: list[float] = []

        def _p95_latency() -> float | None:
            if not _latency_history:
                return None
            return sorted(_latency_history)[int(len(_latency_history) * 0.95)]

        # ── 인퍼런스 스레드 ──────────────────────────────────────────────────
        def _inference_loop():
            while not infer_stop.is_set():
                with queue_lock:
                    qsize = len(processed_action_queue)
                    idx_before = executed_count[0]
                    # RTC prefix는 postprocess 전 original action 공간이어야 한다.
                    prev_left_over = (
                        np.array(list(original_action_queue), dtype=np.float32)
                        if original_action_queue else None
                    )

                if qsize > _INFER_QUEUE_THRESHOLD:
                    infer_skipped[0] += 1
                    time.sleep(0.005)
                    continue

                with obs_lock:
                    obs = latest_obs.copy()

                if obs['top'] is None:
                    time.sleep(0.005)
                    continue

                try:
                    # P95 latency로 delay 추정 (첫 추론은 0)
                    p95 = _p95_latency()
                    delay = math.ceil(p95 / period) if p95 else 0

                    t_start = time.perf_counter()
                    original_chunk, processed_chunk = self._model.get_action_chunk(
                        top_image=obs['top'],
                        wrist_image=obs['wrist'],
                        state=obs['state'],
                        task=task,
                        robot_type=_ROBOT_TYPE,
                        inference_delay=delay,
                        prev_chunk_left_over=prev_left_over,
                    )
                    infer_s = time.perf_counter() - t_start
                    _latency_history.append(infer_s)
                    if len(_latency_history) > 50:
                        _latency_history.pop(0)

                    real_delay = round(infer_s / period)

                    with queue_lock:
                        q_before = len(processed_action_queue)
                        consumed_during_infer = max(0, executed_count[0] - idx_before)
                        if abs(consumed_during_infer - real_delay) <= 1:
                            base_delay = consumed_during_infer
                        else:
                            base_delay = real_delay
                        actual_delay = base_delay + _RTC_DELAY_OFFSET_STEPS
                        actual_delay = max(0, min(actual_delay, len(processed_chunk)))

                        # lerobot ActionQueue RTC mode: delay만 제거하고 chunk tail 전체로 replace.
                        original_action_queue.clear()
                        processed_action_queue.clear()
                        queued_original = original_chunk[actual_delay:]
                        queued_processed = processed_chunk[actual_delay:]
                        original_action_queue.extend(queued_original)
                        processed_action_queue.extend(queued_processed)
                        q_after = len(processed_action_queue)

                        grip_seq = queued_processed[:, 5] if len(queued_processed) else np.array([], dtype=np.float32)
                        grip_head = ','.join(f'{v:.1f}' for v in grip_seq[:12])
                        grip_tail = ','.join(f'{v:.1f}' for v in grip_seq[-6:])
                        grip_min = float(np.min(grip_seq)) if len(grip_seq) else float('nan')
                        grip_max = float(np.max(grip_seq)) if len(grip_seq) else float('nan')

                    infer_count[0] += 1
                    p95_ms = f'{p95*1000:.0f}ms' if p95 else 'N/A'
                    self.get_logger().info(
                        f'[infer #{infer_count[0]}] '
                        f'infer={infer_s*1000:.0f}ms '
                        f'p95={p95_ms} '
                        f'delay={actual_delay} base_delay={base_delay} offset={_RTC_DELAY_OFFSET_STEPS} '
                        f'real_delay={real_delay} consumed={consumed_during_infer} '
                        f'prev_len={len(prev_left_over) if prev_left_over is not None else 0} '
                        f'queue {q_before}->{q_after} '
                        f'grip_minmax={grip_min:.1f}/{grip_max:.1f} '
                        f'grip_head=[{grip_head}] grip_tail=[{grip_tail}] '
                        f'(skip={infer_skipped[0]})'
                    )
                    infer_skipped[0] = 0
                except Exception as e:
                    infer_error[0] = e
                    infer_stop.set()
                    return

        infer_thread = threading.Thread(target=_inference_loop, daemon=True)

        try:
            # 첫 관찰값 설정 후 인퍼런스 스레드 시작
            top_img   = top_cam.read()
            wrist_img = wrist_cam.read()
            state     = robot.get_positions()
            with obs_lock:
                latest_obs = {'top': top_img, 'wrist': wrist_img, 'state': state}

            infer_thread.start()

            # 첫 chunk가 채워질 때까지 대기 (최대 60초)
            deadline = time.time() + 60.0
            while time.time() < deadline:
                if goal_handle.is_cancel_requested:
                    return
                if infer_error[0]:
                    raise infer_error[0]
                with queue_lock:
                    if processed_action_queue:
                        break
                time.sleep(0.05)
            else:
                raise RuntimeError('Inference did not produce actions within 60s')

            prev_action_interp = None  # 보간을 위한 이전 액션

            # ── 제어 루프 (30Hz 정책, 150Hz 보간 전송) ─────────────────────
            while not goal_handle.is_cancel_requested:
                t0 = time.time()

                if infer_error[0]:
                    raise infer_error[0]

                # 최신 관찰값 업데이트 (인퍼런스 스레드가 즉시 사용)
                top_img   = top_cam.read()
                wrist_img = wrist_cam.read()
                state     = robot.get_positions()
                with obs_lock:
                    latest_obs = {'top': top_img, 'wrist': wrist_img, 'state': state}

                # ── 관절값 60초 기록 ──────────────────────────────────────
                if not joint_log_saved:
                    elapsed = time.time() - joint_log_start
                    joint_log.append((elapsed, state.copy()))
                    if elapsed >= _JOINT_LOG_SECS:
                        data = np.array([[t] + s.tolist() for t, s in joint_log])
                        np.save(_JOINT_LOG_PATH, data)
                        self.get_logger().info(
                            f'Joint log saved to {_JOINT_LOG_PATH} '
                            f'({len(joint_log)} frames, {elapsed:.1f}s)'
                        )
                        joint_log_saved = True

                # ── 홈 포지션 감지 + VLM task 완료 판단 ──────────────────
                in_home = all(
                    lo <= state[i] <= hi
                    for i, (lo, hi) in _HOME_RANGE.items()
                )
                if not in_home:
                    if not has_left_home:
                        has_left_home = True
                        self.get_logger().info('Left initial position. Home detection now active.')
                    if home_since is not None:
                        self.get_logger().info('Left home position.')
                    home_since = None
                else:
                    if not has_left_home:
                        pass  # 작업 시작 전 → 무시
                    elif home_since is None:
                        home_since = time.time()
                        self.get_logger().info('Home position entered.')
                    elif time.time() - home_since >= _HOME_DWELL_S:
                        self.get_logger().info(
                            f'Home position held for {_HOME_DWELL_S}s. '
                            'Asking VLM for task completion...'
                        )
                        feedback.status = 'Checking task completion via VLM...'
                        goal_handle.publish_feedback(feedback)
                        vlm_host = self.get_parameter('vlm_host').value
                        try:
                            complete, vlm_answer = _vlm_check_task_complete(top_img, task, vlm_host)
                            self.get_logger().info(
                                f'VLM answer: "{vlm_answer}" → complete={complete}'
                            )
                        except Exception as e:
                            self.get_logger().warn(f'VLM check failed: {e}. Continuing.')
                            complete = False

                        if complete:
                            self.get_logger().info('VLM confirmed task complete.')
                            task_complete = True
                            raise _TaskComplete()
                        else:
                            self.get_logger().info('VLM says task not complete. Continuing.')
                            home_since = None

                # ── 다음 액션 실행 (보간 포함, 큐 없으면 홀드) ───────────
                with queue_lock:
                    qsize = len(processed_action_queue)
                    if processed_action_queue:
                        action = processed_action_queue.popleft()
                        if original_action_queue:
                            original_action_queue.popleft()
                        executed_count[0] += 1
                    else:
                        action = None

                if action is not None:
                    step += 1
                    feedback.status = f'step {step}'
                    goal_handle.publish_feedback(feedback)

                    if step % 10 == 0:
                        self.get_logger().info(
                            f'[ctrl] step={step} queue={qsize} '
                            f'state=[{",".join(f"{v:.1f}" for v in state[:3])},...] '
                            f'action=[{",".join(f"{v:.1f}" for v in action[:3])},...] '
                            f'diff=[{",".join(f"{v:.1f}" for v in (action-state)[:3])}] '
                            f'grip state={state[5]:.1f} action={action[5]:.1f} diff={action[5]-state[5]:.1f}'
                        )

                    # 이전 액션 → 현재 액션 사이를 선형 보간해 150Hz로 전송
                    src = prev_action_interp if prev_action_interp is not None else action
                    for i in range(1, _INTERPOLATION_MULT + 1):
                        if goal_handle.is_cancel_requested:
                            break
                        t_interp = i / _INTERPOLATION_MULT
                        interp = src * (1.0 - t_interp) + action * t_interp
                        robot.set_positions(interp)
                        time.sleep(_SUB_PERIOD)

                    prev_action_interp = action.copy()
                else:
                    self.get_logger().warn(f'[ctrl] step={step} queue EMPTY — holding position')

                # 보간 루프(5 × 6.67ms)가 이미 ~33ms를 소비하므로 별도 sleep 불필요
                # 큐가 비어 hold 상태일 때만 sleep
                if action is None:
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
                self.get_logger().info(f'{reason} — returning to initial position ...')
                try:
                    robot.return_to_position(initial_pos, duration_s=3.0)
                except Exception as e:
                    self.get_logger().warn(f'Return to initial position failed: {e}')
            robot.close()
            self.get_logger().info('Hardware disconnected.')


def main(args=None):
    rp.init(args=args)
    node = SingleArmControllerNode()
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
