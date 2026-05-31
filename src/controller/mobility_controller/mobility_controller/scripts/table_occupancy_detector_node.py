#!/usr/bin/env python3
"""table_occupancy_detector_node — patrol perception 서버.

설계 SoT: docs/moca_patrol_design.md §3.

책임:
  - /camera/image_raw 최근 프레임 cache (last frame, last_ts)
  - /table_occupancy/scan 서비스 (ScanTable.srv) 응답
  - 호출 시점 1프레임 grab → YOLOv8 person inference → occupancy 분류
  - 지속 분석 X (호출 시점만, 부하 ↓)

분류 룰 (디자인 §3.2):
  person_count >= 1                  → "occupied"
  person_count == 0 ∧ dishes==True   → "finished" (M3)
  person_count == 0 ∧ dishes==False  → "empty"
  (프레임/모델 없음)                 → "unknown"

의존:
  - sensor_msgs, cv_bridge (apt)
  - ultralytics (pip, optional — 미설치 시 unknown 응답)
  - YOLO weights: mobility_controller share/models/yolo/yolov8n.pt
"""

import os
import threading
from pathlib import Path
from typing import Optional

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from cv_bridge import CvBridge
from sensor_msgs.msg import Image

from dobi_npc_msgs.srv import ScanTable

# ultralytics 는 선택 의존 (pip 설치 필요). 미설치 환경에서도 노드는 떠야 함
# (M1 ~ M2 W1 단계 dummy 동작 + M2 W2 실 detector 활성화).
try:
    from ultralytics import YOLO  # type: ignore
    YOLO_AVAILABLE = True
except ImportError:
    YOLO = None  # type: ignore
    YOLO_AVAILABLE = False


def _default_yolo_weights() -> str:
    """YOLO weights 기본 경로 — env > package share > 빈 문자열."""
    env = os.environ.get('MOCA_YOLO_WEIGHTS', '').strip()
    if env:
        return os.path.expanduser(env)
    try:
        candidate = (
            Path(get_package_share_directory('mobility_controller')) /
            'models' / 'yolo' / 'yolov8n.pt'
        )
        if candidate.is_file():
            return str(candidate)
    except Exception:
        pass
    return ''


class TableOccupancyDetector(Node):
    """patrol_scheduler 가 호출하는 perception 서비스 노드."""

    def __init__(self):
        super().__init__('table_occupancy_detector')

        # ---- 파라미터 ----
        self.declare_parameter('yolo_weights_path', _default_yolo_weights())
        self.declare_parameter('confidence_threshold', 0.5)
        self.declare_parameter('person_class_id', 0)  # COCO
        self.declare_parameter('image_topic', '/camera/image_raw')
        self.declare_parameter('dishes_enabled', False)
        self.declare_parameter(
            'frame_stale_sec', 2.0,
            descriptor=None)  # 마지막 프레임이 이보다 오래되면 stale → unknown
        self.declare_parameter('scan_service_name', '/table_occupancy/scan')

        # ---- 프레임 cache (별 thread 에서 update / scan 콜백에서 read) ----
        self._frame_lock = threading.Lock()
        self._last_frame = None
        self._last_frame_ts: Optional[rclpy.time.Time] = None
        self.bridge = CvBridge()

        # ---- YOLO 모델 lazy load ----
        self._model = None
        self._model_load_attempted = False
        self._try_load_model()

        # ---- ROS ----
        image_topic = str(self.get_parameter('image_topic').value)
        self.sub_image = self.create_subscription(
            Image, image_topic, self._on_image, 10)
        self.srv_scan = self.create_service(
            ScanTable,
            str(self.get_parameter('scan_service_name').value),
            self._on_scan)

        self.get_logger().info(
            f'table_occupancy_detector ready: '
            f'image_topic={image_topic} '
            f'yolo_available={YOLO_AVAILABLE} model_loaded={self._model is not None}')

    # ─────────── YOLO 로드 ───────────

    def _try_load_model(self) -> None:
        if self._model_load_attempted:
            return
        self._model_load_attempted = True
        if not YOLO_AVAILABLE:
            self.get_logger().warn(
                'ultralytics 미설치 — detector 는 unknown 응답 모드. '
                '활성화: pip install --user ultralytics')
            return
        weights = str(self.get_parameter('yolo_weights_path').value)
        if not weights or not os.path.isfile(weights):
            self.get_logger().warn(
                f'YOLO weights 없음: {weights!r}. '
                f'detector 는 unknown 응답 모드. '
                f'활성화: -p yolo_weights_path:=<path> 또는 env MOCA_YOLO_WEIGHTS')
            return
        try:
            self._model = YOLO(weights)
            self.get_logger().info(f'YOLO loaded: {weights}')
        except Exception as e:
            self.get_logger().error(
                f'YOLO 로드 실패 ({type(e).__name__}): {e}. '
                f'detector 는 unknown 응답 모드.')
            self._model = None

    # ─────────── 카메라 ───────────

    def _on_image(self, msg: Image) -> None:
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            # 너무 자주 warn 안 나게 throttle 권장 — 일단 단순
            self.get_logger().warn(
                f'image conversion failed: {e}', throttle_duration_sec=5.0)
            return
        with self._frame_lock:
            self._last_frame = frame
            self._last_frame_ts = self.get_clock().now()

    def _frame_age_sec(self) -> float:
        if self._last_frame_ts is None:
            return float('inf')
        now = self.get_clock().now()
        return (now - self._last_frame_ts).nanoseconds / 1e9

    # ─────────── 서비스 핸들러 ───────────

    def _on_scan(self, request: ScanTable.Request,
                 response: ScanTable.Response) -> ScanTable.Response:
        table_id = request.table_id or ''
        self.get_logger().info(f'scan request: table_id={table_id!r}')

        # 1. 프레임 cache 확인
        stale_sec = float(self.get_parameter('frame_stale_sec').value)
        with self._frame_lock:
            frame = self._last_frame.copy() if self._last_frame is not None else None
        age = self._frame_age_sec()

        if frame is None:
            return self._fail(response, 'unknown', error='no_frame')
        if age > stale_sec:
            return self._fail(
                response, 'unknown',
                error=f'stale_frame:{age:.1f}s>{stale_sec:.1f}s')

        # 2. 모델 확인 (lazy retry)
        if self._model is None:
            self._try_load_model()
        if self._model is None:
            return self._fail(response, 'unknown', error='no_model')

        # 3. YOLO inference
        try:
            conf = float(self.get_parameter('confidence_threshold').value)
            person_class = int(self.get_parameter('person_class_id').value)
            results = self._model(
                frame, classes=[person_class], conf=conf, verbose=False)
            persons = results[0].boxes if results else None
            if persons is None:
                person_count = 0
                max_conf = 0.0
            else:
                person_count = int(len(persons))
                if person_count > 0:
                    try:
                        max_conf = float(persons.conf.max().item())
                    except Exception:
                        max_conf = float(conf)
                else:
                    max_conf = 0.9  # empty 추론 기본 신뢰도
        except Exception as e:
            self.get_logger().error(
                f'YOLO inference 실패 ({type(e).__name__}): {e}')
            return self._fail(
                response, 'unknown',
                error=f'inference_error:{type(e).__name__}', success=False)

        # 4. dishes (M3) — 현재 항상 false
        dishes_detected = False
        if bool(self.get_parameter('dishes_enabled').value):
            # M3: custom YOLO dishes model 호출
            pass

        # 5. occupancy 분류
        if person_count >= 1:
            occupancy = 'occupied'
        elif dishes_detected:
            occupancy = 'finished'
        else:
            occupancy = 'empty'

        response.success = True
        response.occupancy = occupancy
        response.person_count = person_count
        response.dishes_detected = dishes_detected
        response.confidence = max_conf
        response.error = ''
        self.get_logger().info(
            f'scan result {table_id}: occupancy={occupancy} '
            f'person={person_count} conf={max_conf:.2f}')
        return response

    @staticmethod
    def _fail(
        response: ScanTable.Response,
        occupancy: str,
        error: str = '',
        success: bool = True,
    ) -> ScanTable.Response:
        """unknown 응답 빌더 — frame/model 없음은 success=True + occupancy=unknown
        으로 두는 게 scheduler 입장에서 자연스러움 (호출은 성공한 것)."""
        response.success = success
        response.occupancy = occupancy
        response.person_count = 0
        response.dishes_detected = False
        response.confidence = 0.0
        response.error = error
        return response


def main(args=None):
    rclpy.init(args=args)
    node = TableOccupancyDetector()
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
