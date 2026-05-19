"""test_table_occupancy_detector — 서비스 핸들러 + YOLO mock 단위 테스트.

전략: rclpy.init() + 실 Node + ultralytics 미설치 환경에서도 작동하는 mock model.

실행:
  source install/setup.bash
  python3 -m pytest src/dobi_npc/dobi_npc_bringup/test/test_table_occupancy_detector.py -v
"""

from unittest.mock import MagicMock

import numpy as np
import pytest
import rclpy

from dobi_npc_msgs.srv import ScanTable

from dobi_npc_bringup.table_occupancy_detector_node import (
    TableOccupancyDetector,
)


@pytest.fixture(scope='module')
def rclpy_setup():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.fixture
def detector(rclpy_setup):
    """프레임/모델 모두 비어있는 깨끗한 detector 인스턴스."""
    d = TableOccupancyDetector()
    # YOLO weights 가 environment 에서 자동 로드됐을 수도 — 명시적으로 비움
    d._model = None
    d._last_frame = None
    d._last_frame_ts = None
    yield d
    d.destroy_node()


def _new_request(table_id: str = 'T01') -> ScanTable.Request:
    req = ScanTable.Request()
    req.table_id = table_id
    return req


def _new_response() -> ScanTable.Response:
    return ScanTable.Response()


def _fake_frame(w: int = 640, h: int = 480) -> np.ndarray:
    """검증용 더미 BGR 프레임."""
    return np.zeros((h, w, 3), dtype=np.uint8)


# ──────────────── 1. 프레임/모델 부재 ────────────────

def test_no_frame_returns_unknown(detector):
    """프레임 cache 없음 → success=True + occupancy=unknown + error=no_frame."""
    resp = detector._on_scan(_new_request('T01'), _new_response())
    assert resp.success is True
    assert resp.occupancy == 'unknown'
    assert resp.error == 'no_frame'
    assert resp.person_count == 0
    assert resp.confidence == 0.0


def test_no_model_returns_unknown(detector):
    """프레임 있음 + 모델 없음 → unknown + error=no_model."""
    detector._last_frame = _fake_frame()
    detector._last_frame_ts = detector.get_clock().now()
    # _try_load_model 이 model 을 채울 가능성이 있으므로 _model_load_attempted=True 유지
    # 하여 재시도 차단
    detector._model_load_attempted = True
    resp = detector._on_scan(_new_request('T01'), _new_response())
    assert resp.success is True
    assert resp.occupancy == 'unknown'
    assert resp.error == 'no_model'


def test_stale_frame_returns_unknown(detector):
    """frame_stale_sec 보다 오래된 프레임 → unknown + error stale_frame."""
    from rclpy.duration import Duration
    detector._last_frame = _fake_frame()
    # 매우 오래된 timestamp — 현 시각보다 10초 이전
    detector._last_frame_ts = detector.get_clock().now() - Duration(seconds=10)
    resp = detector._on_scan(_new_request('T01'), _new_response())
    assert resp.success is True
    assert resp.occupancy == 'unknown'
    assert resp.error.startswith('stale_frame:')


# ──────────────── 2. YOLO 결과별 분류 ────────────────

class _FakeBox:
    """ultralytics.engine.results.Boxes 의 최소 mock — len() + .conf.max() 지원."""
    def __init__(self, n: int, confs):
        self._n = n
        self._confs = confs

    def __len__(self):
        return self._n


def _fake_results(person_count: int, confs):
    """ultralytics YOLO model(frame, ...) 의 반환 mock — results[0].boxes 접근."""
    boxes = _FakeBox(person_count, confs)
    # persons.conf.max().item() 접근 path
    conf_mock = MagicMock()
    if person_count > 0:
        conf_mock.max.return_value.item.return_value = float(max(confs))
    boxes.conf = conf_mock
    item = MagicMock()
    item.boxes = boxes
    return [item]


def test_yolo_person_detected_returns_occupied(detector):
    """mock YOLO 1 person → occupancy=occupied + person_count=1."""
    detector._last_frame = _fake_frame()
    detector._last_frame_ts = detector.get_clock().now()
    detector._model = MagicMock()
    detector._model.return_value = _fake_results(person_count=1, confs=[0.87])
    detector._model_load_attempted = True

    resp = detector._on_scan(_new_request('T02'), _new_response())
    assert resp.success is True
    assert resp.occupancy == 'occupied'
    assert resp.person_count == 1
    assert resp.confidence == pytest.approx(0.87, abs=0.01)
    assert resp.dishes_detected is False
    assert resp.error == ''


def test_yolo_multiple_persons(detector):
    """3명 검출 → occupied + person_count=3 + confidence = max bbox."""
    detector._last_frame = _fake_frame()
    detector._last_frame_ts = detector.get_clock().now()
    detector._model = MagicMock()
    detector._model.return_value = _fake_results(
        person_count=3, confs=[0.6, 0.92, 0.71])
    detector._model_load_attempted = True

    resp = detector._on_scan(_new_request('T03'), _new_response())
    assert resp.occupancy == 'occupied'
    assert resp.person_count == 3
    assert resp.confidence == pytest.approx(0.92, abs=0.01)


def test_yolo_zero_persons_returns_empty(detector):
    """0명 + dishes_enabled=false → empty + default conf 0.9."""
    detector._last_frame = _fake_frame()
    detector._last_frame_ts = detector.get_clock().now()
    detector._model = MagicMock()
    detector._model.return_value = _fake_results(person_count=0, confs=[])
    detector._model_load_attempted = True

    resp = detector._on_scan(_new_request('T04'), _new_response())
    assert resp.occupancy == 'empty'
    assert resp.person_count == 0
    assert resp.dishes_detected is False
    # empty 추론 기본 신뢰도 0.9 (디자인 §3.2 step 6)
    assert resp.confidence == pytest.approx(0.9, abs=0.01)
    assert resp.error == ''


def test_yolo_inference_exception_returns_unknown(detector):
    """모델 호출 중 예외 → success=False + occupancy=unknown + error=inference_error:..."""
    detector._last_frame = _fake_frame()
    detector._last_frame_ts = detector.get_clock().now()
    detector._model = MagicMock()
    detector._model.side_effect = RuntimeError('mock cuda OOM')
    detector._model_load_attempted = True

    resp = detector._on_scan(_new_request('T05'), _new_response())
    assert resp.success is False
    assert resp.occupancy == 'unknown'
    assert resp.error.startswith('inference_error:')


def test_yolo_empty_results_list_returns_empty(detector):
    """YOLO 가 빈 list 반환 (results=[]) — boxes None → person_count=0 → empty."""
    detector._last_frame = _fake_frame()
    detector._last_frame_ts = detector.get_clock().now()
    detector._model = MagicMock()
    detector._model.return_value = []   # 빈 결과
    detector._model_load_attempted = True

    resp = detector._on_scan(_new_request('T01'), _new_response())
    assert resp.success is True
    assert resp.occupancy == 'empty'
    assert resp.person_count == 0


# ──────────────── 3. 프레임 cache 메커니즘 ────────────────

def test_frame_age_inf_when_no_frame(detector):
    """프레임 없음 → age = inf."""
    detector._last_frame = None
    detector._last_frame_ts = None
    assert detector._frame_age_sec() == float('inf')


def test_frame_age_zero_just_now(detector):
    """방금 받은 프레임 → age ≈ 0."""
    detector._last_frame = _fake_frame()
    detector._last_frame_ts = detector.get_clock().now()
    age = detector._frame_age_sec()
    assert age < 0.5   # 테스트 환경 noise 고려
