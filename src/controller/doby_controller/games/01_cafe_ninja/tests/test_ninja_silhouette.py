"""ninja_silhouette 모듈 테스트 — mediapipe는 monkeypatch로 mock."""
import numpy as np
import pytest

from ninja_silhouette import SilhouetteResult


class TestSilhouetteResult:
    def test_default_empty(self):
        r = SilhouetteResult()
        assert r.person_mask is None
        assert r.eye_points == []
        assert r.detected is False

    def test_with_values(self):
        mask = np.full((480, 640), 255, dtype=np.uint8)
        r = SilhouetteResult(person_mask=mask, eye_points=[(100, 200), (200, 200)], detected=True)
        assert r.person_mask is mask
        assert len(r.eye_points) == 2
        assert r.detected is True


from ninja_silhouette import NinjaSilhouette


class TestNinjaSilhouetteInit:
    def test_init_success(self, monkeypatch):
        """mediapipe 정상일 때 available=True."""
        mock_seg = type("MockSeg", (), {"process": lambda self, img: None})()
        mock_fd = type("MockFD", (), {"process": lambda self, img: None})()

        def fake_selfie(*args, **kwargs):
            return mock_seg

        def fake_face(*args, **kwargs):
            return mock_fd

        monkeypatch.setattr("ninja_silhouette._build_selfie_segmentation", fake_selfie)
        monkeypatch.setattr("ninja_silhouette._build_face_detection", fake_face)

        sil = NinjaSilhouette()
        assert sil.available is True
        assert sil._seg is mock_seg
        assert sil._fd is mock_fd

    def test_init_seg_failure_falls_back(self, monkeypatch):
        """selfie_segmentation 빌드 실패 → available=False."""
        def raise_err(*args, **kwargs):
            raise RuntimeError("mediapipe seg not available")

        def fake_face(*args, **kwargs):
            return type("MockFD", (), {})()

        monkeypatch.setattr("ninja_silhouette._build_selfie_segmentation", raise_err)
        monkeypatch.setattr("ninja_silhouette._build_face_detection", fake_face)

        sil = NinjaSilhouette()
        assert sil.available is False

    def test_init_face_failure_keeps_seg(self, monkeypatch):
        """face_detection 실패해도 seg가 살아있으면 available=True (eye reveal만 비활성)."""
        mock_seg = type("MockSeg", (), {"process": lambda self, img: None})()

        def fake_selfie(*args, **kwargs):
            return mock_seg

        def raise_err(*args, **kwargs):
            raise RuntimeError("face detection failed")

        monkeypatch.setattr("ninja_silhouette._build_selfie_segmentation", fake_selfie)
        monkeypatch.setattr("ninja_silhouette._build_face_detection", raise_err)

        sil = NinjaSilhouette()
        assert sil.available is True
        assert sil._fd is None

    def test_close_cleans_resources(self, monkeypatch):
        """close() → 리소스 해제 + available=False."""
        mock_seg = type("MockSeg", (), {"close": lambda self: None})()
        mock_fd = type("MockFD", (), {"close": lambda self: None})()
        monkeypatch.setattr("ninja_silhouette._build_selfie_segmentation", lambda **kw: mock_seg)
        monkeypatch.setattr("ninja_silhouette._build_face_detection", lambda **kw: mock_fd)

        sil = NinjaSilhouette()
        assert sil.available is True

        sil.close()
        assert sil.available is False
        assert sil._seg is None
        assert sil._fd is None


class TestNinjaSilhouetteProcess:
    @pytest.fixture
    def fake_frame(self):
        return np.full((480, 640, 3), 128, dtype=np.uint8)

    def _make_sil(self, monkeypatch, seg_mask=None, eye_norm_points=None, fd_present=True,
                  nose_norm=None, mouth_norm=None):
        """공통 헬퍼: seg/fd mock + NinjaSilhouette 인스턴스 반환.

        keypoints 순서: [right_eye, left_eye, nose, mouth, right_ear, left_ear].
        eye_norm_points / nose_norm / mouth_norm 중 제공된 만큼 keypoint 리스트로 합쳐 mock.
        """
        class FakeSegResult:
            segmentation_mask = seg_mask

        class FakeKeypoint:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class FakeLocation:
            def __init__(self, kps):
                self.relative_keypoints = kps

        class FakeDetection:
            def __init__(self, kps):
                self.location_data = FakeLocation(kps)

        # keypoint 리스트 조립
        kps_list = None
        if eye_norm_points is not None or nose_norm is not None or mouth_norm is not None:
            kps_list = []
            for p in (eye_norm_points or []):
                kps_list.append(FakeKeypoint(*p))
            # eye가 1개만 있어도 nose는 idx=2가 되어야 하므로 padding
            while len(kps_list) < 2:
                kps_list.append(FakeKeypoint(-1, -1))  # 화면 밖 → process()에서 클립
            if nose_norm is not None:
                kps_list.append(FakeKeypoint(*nose_norm))
            if mouth_norm is not None:
                while len(kps_list) < 3:
                    kps_list.append(FakeKeypoint(-1, -1))
                kps_list.append(FakeKeypoint(*mouth_norm))

        class FakeFDResult:
            detections = [FakeDetection(kps_list)] if kps_list is not None else None

        mock_seg = type("MockSeg", (), {"process": lambda self, img: FakeSegResult()})()
        mock_fd = type("MockFD", (), {"process": lambda self, img: FakeFDResult()})()

        monkeypatch.setattr("ninja_silhouette._build_selfie_segmentation", lambda **kw: mock_seg)
        if fd_present:
            monkeypatch.setattr("ninja_silhouette._build_face_detection", lambda **kw: mock_fd)
        else:
            monkeypatch.setattr("ninja_silhouette._build_face_detection",
                                lambda **kw: (_ for _ in ()).throw(RuntimeError("no fd")))

        return NinjaSilhouette()

    def test_process_person_and_eyes(self, monkeypatch, fake_frame):
        """사람 검출 + 양 눈 + 코 + 입 모두 검출되는 정상 케이스."""
        mask_prob = np.zeros((480, 640), dtype=np.float32)
        mask_prob[100:380, 200:440] = 0.9  # 사람 영역
        sil = self._make_sil(
            monkeypatch, seg_mask=mask_prob,
            eye_norm_points=[(0.45, 0.30), (0.55, 0.30)],
            nose_norm=(0.50, 0.36),
            mouth_norm=(0.50, 0.42),
        )

        r = sil.process(fake_frame)
        assert r.person_mask is not None
        assert r.person_mask.shape == (480, 640)
        assert r.person_mask.dtype == np.uint8
        assert r.person_mask[200, 300] == 255
        assert r.person_mask[10, 10] == 0
        assert len(r.eye_points) == 2
        # (0.45 * 640, 0.30 * 480) ≈ (288, 144)
        assert r.eye_points[0] == (288, 144)
        assert r.eye_points[1] == (352, 144)
        assert r.nose_point == (320, 173)   # 0.50*640, 0.36*480
        assert r.mouth_point == (320, 202)  # 0.50*640, 0.42*480
        assert r.detected is True  # person + mouth_point 둘 다 있음

    def test_process_no_person(self, monkeypatch, fake_frame):
        """사람 미검출 (전부 0)."""
        mask_prob = np.zeros((480, 640), dtype=np.float32)
        sil = self._make_sil(monkeypatch, seg_mask=mask_prob, eye_norm_points=None)
        r = sil.process(fake_frame)
        assert r.person_mask is not None
        assert r.person_mask.sum() == 0
        assert r.eye_points == []
        assert r.detected is False

    def test_process_no_face(self, monkeypatch, fake_frame):
        """사람은 있는데 얼굴 검출 실패."""
        mask_prob = np.full((480, 640), 0.9, dtype=np.float32)
        sil = self._make_sil(monkeypatch, seg_mask=mask_prob, eye_norm_points=None)
        r = sil.process(fake_frame)
        assert r.person_mask.sum() > 0
        assert r.eye_points == []
        assert r.detected is False

    def test_process_no_fd_module(self, monkeypatch, fake_frame):
        """face_detection 빌드 실패 (self._fd=None) — 마스크만 반환."""
        mask_prob = np.full((480, 640), 0.9, dtype=np.float32)
        sil = self._make_sil(monkeypatch, seg_mask=mask_prob, eye_norm_points=None, fd_present=False)
        assert sil._fd is None
        r = sil.process(fake_frame)
        assert r.person_mask.sum() > 0
        assert r.eye_points == []

    def test_process_unavailable_returns_empty(self, monkeypatch, fake_frame):
        """available=False일 때 빈 결과."""
        def raise_err(**kw):
            raise RuntimeError("no seg")
        monkeypatch.setattr("ninja_silhouette._build_selfie_segmentation", raise_err)
        monkeypatch.setattr("ninja_silhouette._build_face_detection", lambda **kw: object())
        sil = NinjaSilhouette()
        assert sil.available is False
        r = sil.process(fake_frame)
        assert r.person_mask is None
        assert r.eye_points == []
        assert r.detected is False

    def test_process_one_eye_only(self, monkeypatch, fake_frame):
        """얼굴 측면 (눈 1개 + 입 검출) → mouth_point 있으면 detected=True."""
        mask_prob = np.full((480, 640), 0.9, dtype=np.float32)
        sil = self._make_sil(
            monkeypatch, seg_mask=mask_prob,
            eye_norm_points=[(0.45, 0.30)],
            mouth_norm=(0.50, 0.42),
        )
        r = sil.process(fake_frame)
        assert len(r.eye_points) == 1
        assert r.eye_points[0] == (288, 144)
        assert r.mouth_point == (320, 202)
        assert r.detected is True  # person + mouth_point → detected

    def test_process_mask_threshold_boundary(self, monkeypatch, fake_frame):
        """마스크 확률이 정확히 threshold(0.5)면 배경, > 0.5면 사람."""
        mask_prob = np.full((480, 640), 0.5, dtype=np.float32)  # 정확히 임계
        mask_prob[100:380, 200:440] = 0.51                       # 약간 위
        sil = self._make_sil(monkeypatch, seg_mask=mask_prob, eye_norm_points=None)
        r = sil.process(fake_frame)
        assert r.person_mask[200, 300] == 255  # 0.51 > 0.5 → 사람
        assert r.person_mask[10, 10] == 0      # 0.5 == 0.5 (np.where는 strict >) → 배경
