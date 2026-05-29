#!/usr/bin/env python3
"""palm_direction_publisher.py — 트리거 토픽을 받으면 MediaPipe palm 감지 → 좌/우 발행.

동작:
  1. /palm_detect_trigger (std_msgs/Empty) 수신 대기 (idle)
  2. 트리거 수신 → TTS "음료 시키신분 손들어주세요" 비동기 재생
  3. 카메라에서 MediaPipe HandLandmarker로 palm 감지
  4. dwell_sec(기본 1.5초) 동안 지속 감지되면 palm 중심 x 좌표로 판별
  5. x > 0.5 → 'right', x <= 0.5 → 'left' 를 /palm_direction 에 1회 발행
  6. 감지 루프만 정지 → 다음 트리거를 기다림 (노드는 유지)

파라미터:
  camera_index              int   4
  dwell_sec                 float 1.5
  topic                     str   /palm_direction
  trigger_topic             str   /palm_detect_trigger
  max_hands                 int   1
  min_detection_confidence  float 0.7
  model_path                str   ""  (비어있으면 repo/models/hand_landmarker.task)
"""

import sys
from pathlib import Path


def _get_ros_param(name: str) -> str | None:
    """sys.argv의 ROS2 args에서 파라미터 값을 추출한다.
    '-p name:=value' 형태와 '--params-file' 형태 모두 처리한다."""
    import yaml as _yaml

    for i, arg in enumerate(sys.argv):
        # -p name:=value 형태
        if arg == '-p' and i + 1 < len(sys.argv):
            kv = sys.argv[i + 1]
            if kv.startswith(f'{name}:='):
                return kv.split(':=', 1)[1]
        # --params-file /tmp/launch_params_xxx 형태
        if arg == '--params-file' and i + 1 < len(sys.argv):
            try:
                with open(sys.argv[i + 1]) as f:
                    data = _yaml.safe_load(f)
                # ROS2 params 파일 구조: {node_name: {ros__parameters: {key: val}}}
                for node_data in data.values():
                    if isinstance(node_data, dict):
                        val = node_data.get('ros__parameters', {}).get(name)
                        if val is not None:
                            return str(val)
            except Exception:
                pass
    return None


def _bootstrap() -> str | None:
    """
    ROS args → YAML(env 섹션) → venv sys.path 삽입.
    YAML의 mediapipe_model_path를 반환한다 (없으면 None).
    """
    import yaml as _yaml  # stdlib — venv 없이 사용 가능

    config_path = _get_ros_param('config_path')
    model_path: str | None = None

    if config_path:
        try:
            with open(config_path) as f:
                cfg = _yaml.safe_load(f)
            env = cfg.get('env', {})
            venv_path  = env.get('venv_path', '')
            model_path = env.get('mediapipe_model_path') or None

            if venv_path:
                site = Path(venv_path).expanduser() / 'lib' / 'python3.12' / 'site-packages'
                if site.is_dir():
                    s = str(site)
                    if s not in sys.path:
                        sys.path.insert(0, s)
                    return model_path
        except Exception:
            pass

    # 폴백: 디렉토리 트리를 탐색해 .venv 자동 발견
    here = Path(__file__).resolve().parent
    for _ in range(10):
        site = here / '.venv' / 'lib' / 'python3.12' / 'site-packages'
        if site.is_dir():
            s = str(site)
            if s not in sys.path:
                sys.path.insert(0, s)
            return model_path
        here = here.parent

    return model_path


_PRELOADED_MODEL_PATH = _bootstrap()

import asyncio
import os
import subprocess
import tempfile
import threading
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python as _mp_tasks
from mediapipe.tasks.python import vision as _mp_vision
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Empty, String
import yaml

_PALM_LM  = [0, 5, 9, 13, 17]
_TTS_TEXT = '음료 시키신분 손들어주세요'


def _synthesize(text: str) -> str | None:
    """edge_tts로 음성을 미리 합성해 임시 파일 경로를 반환한다. 실패 시 None."""
    try:
        import edge_tts

        async def _run(path: str) -> None:
            await edge_tts.Communicate(text, 'ko-KR-SunHiNeural').save(path)

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            path = f.name
        asyncio.run(_run(path))
        return path
    except Exception:
        return None


def _play_or_fallback(cached_path: str | None, text: str) -> None:
    """캐시된 파일 즉시 재생. 없으면 espeak-ng 폴백."""
    if cached_path and os.path.isfile(cached_path):
        try:
            subprocess.run(
                ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', cached_path],
                timeout=30,
            )
            return
        except Exception:
            pass
    try:
        subprocess.run(['espeak-ng', '-v', 'ko', text], timeout=10)
    except Exception:
        pass


def _play_async(cached_path: str | None, text: str) -> None:
    threading.Thread(target=_play_or_fallback, args=(cached_path, text), daemon=True).start()


class PalmDirectionPublisher(Node):

    def __init__(self):
        super().__init__('palm_direction_publisher')

        self.declare_parameter('config_path',              '')
        self.declare_parameter('dwell_sec',                1.5)
        self.declare_parameter('topic',                    '/palm_direction')
        self.declare_parameter('trigger_topic',            '/palm_detect_trigger')
        self.declare_parameter('max_hands',                1)
        self.declare_parameter('min_detection_confidence', 0.7)
        self.declare_parameter('model_path',               '')

        config_path   = str(self.get_parameter('config_path').value)
        self._dwell   = float(self.get_parameter('dwell_sec').value)
        topic         = str(self.get_parameter('topic').value)
        trigger_topic = str(self.get_parameter('trigger_topic').value)
        max_hands     = int(self.get_parameter('max_hands').value)
        min_conf      = float(self.get_parameter('min_detection_confidence').value)
        model_path    = str(self.get_parameter('model_path').value)

        if not config_path:
            raise RuntimeError('config_path 파라미터가 비어있습니다.')
        with open(config_path) as f:
            _cfg = yaml.safe_load(f)
        cam_idx = int(_cfg['cameras']['palm_index'])

        if not model_path:
            model_path = _PRELOADED_MODEL_PATH or ''
        if not model_path or not os.path.isfile(model_path):
            raise FileNotFoundError(
                f'mediapipe 모델 파일 없음: "{model_path}". '
                f'act_serving_config.yaml의 env.mediapipe_model_path 또는 '
                f'ROS 파라미터 model_path를 확인하세요.'
            )

        opts = _mp_vision.HandLandmarkerOptions(
            base_options=_mp_tasks.BaseOptions(model_asset_path=model_path),
            running_mode=_mp_vision.RunningMode.IMAGE,
            num_hands=max_hands,
            min_hand_detection_confidence=min_conf,
            min_tracking_confidence=0.5,
        )
        self._detector = _mp_vision.HandLandmarker.create_from_options(opts)

        self._pub = self.create_publisher(String, topic, 10)
        self.create_subscription(Empty, trigger_topic, self._on_trigger, 10)

        self._cap = cv2.VideoCapture(cam_idx)
        if not self._cap.isOpened():
            raise RuntimeError(f'카메라 열기 실패: index={cam_idx}')

        # 감지 상태 플래그 (트리거 전까지 idle)
        self._detect_flag  = threading.Event()
        self._detect_lock  = threading.Lock()
        self._detecting    = False

        # 노드 시작 시 TTS 미리 합성 (백그라운드) → 트리거 수신 시 즉시 재생
        self._tts_path: str | None = None
        self._tts_ready = threading.Event()
        threading.Thread(target=self._presynthesize_tts, daemon=True, name='tts_synth').start()

        self._thread = threading.Thread(target=self._worker, daemon=True, name='palm_detect')
        self._thread.start()

        self.get_logger().info(
            f'대기 중 | camera={cam_idx} dwell={self._dwell}s '
            f'trigger={trigger_topic} → {topic}'
        )

    def _presynthesize_tts(self) -> None:
        self.get_logger().info('TTS 사전 합성 시작...')
        self._tts_path = _synthesize(_TTS_TEXT)
        if self._tts_path:
            self.get_logger().info('TTS 사전 합성 완료 — 트리거 시 즉시 재생 가능')
        else:
            self.get_logger().warn('TTS 사전 합성 실패 — espeak-ng 폴백 사용')
        self._tts_ready.set()

    def _on_trigger(self, _msg: Empty):
        with self._detect_lock:
            if self._detecting:
                self.get_logger().warn('이미 감지 중 — 트리거 무시')
                return
            self._detecting = True

        self.get_logger().info('트리거 수신 → palm 감지 시작')
        _play_async(self._tts_path, _TTS_TEXT)
        self._detect_flag.set()

    def _worker(self):
        while rclpy.ok():
            self._detect_flag.wait()      # 트리거 대기 (idle)
            self._detect_flag.clear()
            try:
                self._detect_loop()
            except Exception as exc:
                self.get_logger().error(f'감지 루프 오류: {exc}')
            finally:
                with self._detect_lock:
                    self._detecting = False
                self.get_logger().info('감지 완료 → idle 상태로 복귀')

    def _detect_loop(self):
        detect_start: float | None = None

        while rclpy.ok():
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = self._detector.detect(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            )

            if result.hand_landmarks:
                if detect_start is None:
                    detect_start = time.monotonic()
                    self.get_logger().info('palm 감지 — 타이머 시작')

                if time.monotonic() - detect_start >= self._dwell:
                    lms  = result.hand_landmarks[0]
                    cx   = sum(lms[i].x for i in _PALM_LM) / len(_PALM_LM)
                    side = 'right' if cx > 0.5 else 'left'
                    msg  = String()
                    msg.data = side
                    self._pub.publish(msg)
                    self.get_logger().info(f'발행: {side!r} (cx={cx:.3f})')
                    return          # 감지 루프 종료 → worker가 idle로 복귀
            else:
                if detect_start is not None:
                    self.get_logger().debug('palm 소실 — 타이머 리셋')
                detect_start = None

    def destroy_node(self):
        self._detect_flag.set()   # worker 스레드 언블로킹
        self._thread.join(timeout=2.0)
        self._detector.close()
        self._cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PalmDirectionPublisher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
