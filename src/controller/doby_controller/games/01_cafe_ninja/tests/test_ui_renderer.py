"""ui_renderer apply_silhouette 및 헬퍼 테스트."""
import numpy as np
import pytest

import ui_renderer as ui


class TestBuildDiskMask:
    def test_basic_disk(self):
        """반지름 10, feather 0인 원형 마스크."""
        mask = ui._build_disk_mask((100, 100), center=(50, 50), radius=10, feather=0)
        assert mask.shape == (100, 100)
        assert mask.dtype == np.float32
        assert 0.0 <= mask.min() <= mask.max() <= 1.0
        assert mask[50, 50] == pytest.approx(1.0, abs=0.01)  # 중심
        assert mask[0, 0] == pytest.approx(0.0, abs=0.01)    # 멀리

    def test_disk_with_feather(self):
        """feather > 0이면 외곽이 부드러움."""
        mask = ui._build_disk_mask((100, 100), center=(50, 50), radius=10, feather=5)
        # 중심은 1.0
        assert mask[50, 50] == pytest.approx(1.0, abs=0.01)
        # 반지름 + feather 외부는 거의 0
        assert mask[50, 80] < 0.05

    def test_disk_clipped_to_frame(self):
        """중심이 가장자리여도 크래시 X."""
        mask = ui._build_disk_mask((100, 100), center=(95, 95), radius=20, feather=5)
        assert mask.shape == (100, 100)
        # 화면 안 영역엔 값 있어야 함
        assert mask.sum() > 0


class TestBuildCircularMask:
    def test_from_bbox(self):
        """손 bbox 기준 원형 마스크."""
        # bbox = (x1, y1, x2, y2) — finger_tracker.get_hand_bbox 반환 형식
        bbox = (40, 40, 60, 60)  # 중심 (50,50), 대각선 sqrt(800) ≈ 28
        mask = ui._build_circular_mask((100, 100), bbox=bbox, feather=10)
        assert mask.shape == (100, 100)
        assert mask.dtype == np.float32
        assert mask[50, 50] == pytest.approx(1.0, abs=0.05)

    def test_circular_mask_min_radius(self):
        """bbox 작아도 최소 반지름 80px 보장 (spotlight 가독성)."""
        bbox = (50, 50, 52, 52)  # 매우 작은 bbox
        mask = ui._build_circular_mask((200, 200), bbox=bbox, feather=10, min_radius=80)
        # 반지름 80이므로 (50,50)에서 (130,50)까지 mask 영향 있어야 함
        assert mask[51, 90] > 0.5


class TestApplySilhouetteBasic:
    @pytest.fixture
    def setup_frames(self):
        h, w = 100, 100
        # 카메라: 회색 균일
        camera = np.full((h, w, 3), 128, dtype=np.uint8)
        # 배경(town.jpg 대용): 노란 톤
        bg = np.full((h, w, 3), 0, dtype=np.uint8)
        bg[:, :, 1] = 200
        bg[:, :, 2] = 200
        # 사람 마스크: 중앙 사각형
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[30:70, 30:70] = 255
        return camera, bg, mask

    def test_person_mask_none_fills_with_bg(self, setup_frames):
        """사람 미검출 → frame 전체가 bg_image."""
        camera, bg, _ = setup_frames
        frame = camera.copy()
        ui.apply_silhouette(frame, person_mask=None, eye_points=[], hand_bbox=None, bg_image=bg)
        assert frame[10, 10, 0] == 0
        assert frame[10, 10, 1] == 200
        assert frame[10, 10, 2] == 200
        assert frame[50, 50, 1] == 200

    def test_person_area_is_camera_when_no_mouth(self, setup_frames):
        """mouth_point=None → 사람 영역 = 카메라 그대로 (cover 안 그림), 배경 = bg."""
        camera, bg, mask = setup_frames
        frame = camera.copy()
        ui.apply_silhouette(frame, person_mask=mask, eye_points=[], hand_bbox=None, bg_image=bg)
        # 사람 영역 중앙 (50,50): camera (회색 128)
        assert frame[50, 50, 0] == 128
        assert frame[50, 50, 1] == 128
        # 배경 영역 (10,10): bg 색
        assert frame[10, 10, 1] == 200
        assert frame[10, 10, 2] == 200

    def test_mouth_cover_paints_face(self, setup_frames):
        """mouth_point + nose_point + eye_points 주면 코+입 영역에 검정 마스크."""
        import theme
        camera, bg, mask = setup_frames
        frame = camera.copy()
        ui.apply_silhouette(frame, person_mask=mask,
                            eye_points=[(45, 48), (55, 48)],
                            hand_bbox=None, bg_image=bg,
                            nose_point=(50, 52), mouth_point=(50, 56))
        # mouth 좌표(50, 56) 부근 = 자주톤/검정 마스크 컬러
        assert frame[56, 50, 0] == theme.MASK_COVER_TINT_BGR[0]
        assert frame[56, 50, 1] == theme.MASK_COVER_TINT_BGR[1]
        assert frame[56, 50, 2] == theme.MASK_COVER_TINT_BGR[2]
        # 배경(10, 10)은 그대로 bg
        assert frame[10, 10, 1] == 200


class TestApplySilhouetteReveal:
    @pytest.fixture
    def setup_frames(self):
        h, w = 200, 200
        camera = np.full((h, w, 3), 128, dtype=np.uint8)
        camera[100, 100] = [200, 100, 50]  # 마커 픽셀 (손 영역 중심)
        camera[40, 100] = [10, 20, 30]     # 눈 위치 마커
        bg = np.zeros((h, w, 3), dtype=np.uint8)
        bg[:, :, 1] = 200
        # 사람 마스크: 거의 전체 (마진 5px 제외)
        mask = np.full((h, w), 255, dtype=np.uint8)
        mask[:5, :] = 0
        mask[-5:, :] = 0
        mask[:, :5] = 0
        mask[:, -5:] = 0
        return camera, bg, mask

    def test_hand_reveal_inside_person(self, setup_frames):
        """손 bbox가 사람 영역 안 → 손 중앙은 카메라 픽셀."""
        camera, bg, mask = setup_frames
        frame = camera.copy()
        hand_bbox = (80, 80, 120, 120)
        ui.apply_silhouette(frame, person_mask=mask, eye_points=[],
                            hand_bbox=hand_bbox, bg_image=bg)
        # 손 중심 (100, 100)은 카메라 픽셀 [200, 100, 50]에 가까움
        assert frame[100, 100, 0] > 150
        assert frame[100, 100, 1] < 130

    def test_eye_reveal_inside_person(self, setup_frames):
        """눈 좌표가 사람 영역 안 → 작은 원 안 픽셀이 카메라값."""
        camera, bg, mask = setup_frames
        frame = camera.copy()
        ui.apply_silhouette(frame, person_mask=mask, eye_points=[(100, 40)],
                            hand_bbox=None, bg_image=bg)
        # 눈 중심 (100, 40): 카메라 픽셀 [10, 20, 30]에 가까움
        assert frame[40, 100, 0] < 40
        assert frame[40, 100, 1] < 50

    def test_eye_reveal_outside_person_no_effect(self, setup_frames):
        """눈 좌표가 배경 영역 → reveal 없음 (배경 그대로)."""
        camera, bg, mask = setup_frames
        frame = camera.copy()
        # (2, 2)는 마스크 외부 (배경)
        ui.apply_silhouette(frame, person_mask=mask, eye_points=[(2, 2)],
                            hand_bbox=None, bg_image=bg)
        # 배경 색 (0, 200, 0)
        assert frame[2, 2, 1] == 200

    def test_hand_bbox_none_no_reveal(self, setup_frames):
        """hand_bbox=None + mouth_point=None → 사람 영역 = 카메라 그대로 (cover 미적용)."""
        camera, bg, mask = setup_frames
        frame = camera.copy()
        ui.apply_silhouette(frame, person_mask=mask, eye_points=[],
                            hand_bbox=None, bg_image=bg)
        # 사람 영역 임의 픽셀: camera 마커 [200, 100, 50]
        assert frame[100, 100, 0] == 200
        assert frame[100, 100, 1] == 100
        assert frame[100, 100, 2] == 50
