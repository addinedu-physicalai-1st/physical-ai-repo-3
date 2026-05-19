#!/usr/bin/env python3
"""person_detector — RPi 카메라 영상에서 사람 bbox 검출 → /robot_cam/persons.

W4.5 GEFA 사전 + follow 모드 입력. 카메라 아키텍처 SoT (docs/cafe_npc_camera_architecture.md §3) 의
"노트북 YOLO 노드" 역할을 mediapipe ObjectDetector(efficientdet_lite0)로 구현.

파이프라인:
  1) /robot_cam/image_raw (sensor_msgs/Image) 구독 — RPi v4l2_camera_node 발행
  2) cv_bridge → numpy RGB
  3) mediapipe ObjectDetector(IMAGE 모드, score_threshold) 추론
  4) "person" 카테고리만 필터 → vision_msgs/Detection2DArray 변환
  5) /robot_cam/persons (vision_msgs/Detection2DArray) 발행

Detection2D 필드 매핑:
  - bbox.center.position.x/y : pixel coords (이미지 중심 기준 절대 좌표)
  - bbox.size_x / size_y     : pixel 단위 bbox 너비/높이
  - results[0].hypothesis.class_id = "person"
  - results[0].hypothesis.score    = confidence

follow_controller가 이 메시지를 구독해 가장 큰 person bbox 선택 → cmd_vel 변환.
GEFA decision_rule_node도 향후 같은 토픽에서 자세 추정에 사용 가능.
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

from cv_bridge import CvBridge
from sensor_msgs.msg import CompressedImage, Image
from vision_msgs.msg import (
    BoundingBox2D,
    Detection2D,
    Detection2DArray,
    ObjectHypothesisWithPose,
)


PERSON_CLASS = "person"


class PersonDetectorNode(Node):
    """mediapipe ObjectDetector → vision_msgs/Detection2DArray (person만)."""

    def __init__(self):
        super().__init__('person_detector_node')

        self.declare_parameter('input_topic', '/robot_cam/image_raw')
        self.declare_parameter('output_topic', '/robot_cam/persons')
        self.declare_parameter('model_path', '')           # 빈 값이면 share 기본 경로
        self.declare_parameter('score_threshold', 0.4)
        self.declare_parameter('max_results', 5)
        # 영상 수신 rate 대비 추론 throttle. 0이면 매 프레임 추론.
        # 기본 10Hz — follow 반응성 충분 + CPU 부담 ↓.
        self.declare_parameter('detect_rate_hz', 10.0)
        # WiFi 대역폭 절약 — sensor_msgs/CompressedImage 구독.
        # v4l2_camera_node가 image_transport plugin으로 자동 발행.
        # raw 640x480 rgb8 ~25MB/s → JPEG ~1.5MB/s (15x 절약).
        # input_topic에 "/compressed" 자동 append 안 함 — 명시적 토픽 사용:
        #   True → input_topic + "/compressed"  (예: /robot_cam/image_raw/compressed)
        #   False → input_topic 그대로 (raw Image)
        self.declare_parameter('use_compressed', True)

        in_topic = self.get_parameter('input_topic').value
        out_topic = self.get_parameter('output_topic').value
        model_path = self.get_parameter('model_path').value or self._default_model_path()
        score_thr = float(self.get_parameter('score_threshold').value)
        max_results = int(self.get_parameter('max_results').value)
        self._detect_rate_hz = float(self.get_parameter('detect_rate_hz').value)
        self._use_compressed = bool(self.get_parameter('use_compressed').value)

        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"ObjectDetector 모델 미발견: {model_path}. "
                f"`bash scripts/download_models.sh`로 다운로드 필요."
            )

        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = mp_vision.ObjectDetectorOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.IMAGE,
            score_threshold=score_thr,
            max_results=max_results,
            category_allowlist=[PERSON_CLASS],
        )
        self.detector = mp_vision.ObjectDetector.create_from_options(options)
        self.bridge = CvBridge()

        # Wi-Fi 환경에서 image_transport default RELIABLE QoS 가 packet loss 시
        # 재전송 큐 쌓이며 burst stall 발생 (10초 정지 사고). sub 측을 BEST_EFFORT
        # 로 바꾸면 ACK 안 보냄 → pub 재전송 큐 안 쌓임. latest-frame-only 인 follow
        # 워크로드에 적합. (DDS spec: pub reliable + sub best_effort 매치 OK).
        from rclpy.qos import qos_profile_sensor_data
        if self._use_compressed:
            sub_topic = f"{in_topic}/compressed"
            self.sub = self.create_subscription(
                CompressedImage, sub_topic, self._on_compressed,
                qos_profile_sensor_data)
        else:
            sub_topic = in_topic
            self.sub = self.create_subscription(
                Image, sub_topic, self._on_image, qos_profile_sensor_data)
        self.pub = self.create_publisher(
            Detection2DArray, out_topic, 5)

        self._last_detect = 0.0
        self._frames_seen = 0
        self._frames_detected = 0
        self._persons_total = 0
        self._last_log = time.time()

        self.get_logger().info(
            f"person_detector ready: in={sub_topic} "
            f"({'compressed' if self._use_compressed else 'raw'}) "
            f"out={out_topic} "
            f"model={os.path.basename(model_path)} "
            f"score>={score_thr} max={max_results} "
            f"detect_rate={self._detect_rate_hz:.1f}Hz"
        )

    @staticmethod
    def _default_model_path() -> str:
        share = get_package_share_directory('dobi_npc_emotion')
        return os.path.join(share, 'models', 'efficientdet_lite0.tflite')

    def _on_image(self, msg: Image):
        self._frames_seen += 1
        if self._should_skip():
            return
        try:
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
        except Exception as e:
            self.get_logger().warning(f"cv_bridge 변환 실패: {e}")
            return
        if not isinstance(cv_img, np.ndarray) or cv_img.size == 0:
            return
        self._infer_and_publish(cv_img, msg.header)

    def _on_compressed(self, msg: CompressedImage):
        self._frames_seen += 1
        if self._should_skip():
            return
        try:
            buf = np.frombuffer(msg.data, dtype=np.uint8)
            bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception as e:
            self.get_logger().warning(f"cv2.imdecode 실패: {e}")
            return
        if bgr is None or bgr.size == 0:
            return
        # cv2.imdecode → BGR. mediapipe SRGB는 RGB 기대.
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self._infer_and_publish(rgb, msg.header)

    def _should_skip(self) -> bool:
        """detect_rate_hz throttle. True면 이번 frame skip."""
        if self._detect_rate_hz <= 0:
            return False
        now = time.monotonic()
        if (now - self._last_detect) < (1.0 / self._detect_rate_hz):
            return True
        self._last_detect = now
        return False

    def _infer_and_publish(self, rgb_img: np.ndarray, header):
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_img)
        try:
            result = self.detector.detect(mp_image)
        except Exception as e:
            self.get_logger().warning(f"ObjectDetector.detect 실패: {e}")
            return

        out = Detection2DArray()
        out.header = header  # frame_id, stamp 그대로 forward

        if result.detections:
            self._frames_detected += 1
            for det in result.detections:
                self._persons_total += 1
                d = Detection2D()
                d.header = header
                bb = det.bounding_box
                box = BoundingBox2D()
                # bb.origin_x/y는 좌상단. center = origin + size/2.
                box.center.position.x = float(bb.origin_x + bb.width / 2.0)
                box.center.position.y = float(bb.origin_y + bb.height / 2.0)
                box.center.theta = 0.0
                box.size_x = float(bb.width)
                box.size_y = float(bb.height)
                d.bbox = box
                if det.categories:
                    cat = det.categories[0]
                    hyp = ObjectHypothesisWithPose()
                    hyp.hypothesis.class_id = cat.category_name or PERSON_CLASS
                    hyp.hypothesis.score = float(cat.score)
                    d.results.append(hyp)
                out.detections.append(d)

        self.pub.publish(out)
        self._maybe_log()

    def _maybe_log(self):
        now = time.time()
        if now - self._last_log >= 5.0:
            elapsed = now - self._last_log
            in_hz = self._frames_seen / elapsed
            det_hit = (
                100.0 * self._frames_detected / max(1, self._frames_seen)
            )
            self.get_logger().info(
                f"in={in_hz:.1f}Hz "
                f"detected_frames={self._frames_detected}/{self._frames_seen} "
                f"({det_hit:.0f}%) total_persons={self._persons_total}"
            )
            self._frames_seen = 0
            self._frames_detected = 0
            self._persons_total = 0
            self._last_log = now

    def destroy_node(self):
        if hasattr(self, 'detector') and self.detector is not None:
            try:
                self.detector.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PersonDetectorNode()
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
