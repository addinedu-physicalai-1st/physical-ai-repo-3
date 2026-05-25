"""카페 닌자 — Selfie Segmentation + Face Detection 래퍼.

사람 영역 마스크와 양 눈 keypoint를 한 번에 추출. ui_renderer.apply_silhouette()가
이 결과로 자주톤 그림자 + 손/눈 reveal 합성을 수행한다.

mediapipe.solutions.selfie_segmentation 또는 face_detection이 사용 불가할 경우
self.available = False 로 표시하고 기존 spotlight 방식으로 폴백.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class SilhouetteResult:
    """한 프레임의 silhouette 추론 결과."""
    person_mask: Optional[np.ndarray] = None  # uint8 (H, W), 0~255 (사람=255)
    eye_points: List[Tuple[int, int]] = field(default_factory=list)  # 최대 2개 (oright/left)
    nose_point: Optional[Tuple[int, int]] = None    # 코끝 픽셀 좌표
    mouth_point: Optional[Tuple[int, int]] = None   # 입 픽셀 좌표
    detected: bool = False                    # 사람 + 얼굴 모두 검출


def _build_selfie_segmentation(model_selection: int = 1):
    """mediapipe selfie segmentation 인스턴스 생성. 실패 시 예외 raise."""
    import mediapipe as mp  # 모듈 상단 dual-import 블록에 없는 이유 — 빌드 실패 격리
    return mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=model_selection)


def _build_face_detection(model_selection: int = 0, min_confidence: float = 0.5):
    """mediapipe face detection 인스턴스 생성. 실패 시 예외 raise."""
    import mediapipe as mp
    return mp.solutions.face_detection.FaceDetection(
        model_selection=model_selection, min_detection_confidence=min_confidence
    )


class NinjaSilhouette:
    """카메라 frame → 사람 마스크 + 양 눈 좌표.

    Selfie Seg 빌드 실패 시 self.available=False (게임은 spotlight 폴백).
    Face Detection 빌드 실패는 self._fd=None (사람 그림자만, 눈 reveal 생략).
    """

    def __init__(self, seg_model: int = 1, face_model: int = 0, min_face_confidence: float = 0.5):
        self.available: bool = False
        self._seg = None
        self._fd = None
        self._mask_threshold: float = 0.5

        try:
            self._seg = _build_selfie_segmentation(model_selection=seg_model)
        except Exception as e:
            print(f"⚠️ Selfie Segmentation 빌드 실패: {e} — silhouette 비활성, spotlight 폴백")
            return  # available=False 유지

        try:
            self._fd = _build_face_detection(model_selection=face_model, min_confidence=min_face_confidence)
        except Exception as e:
            print(f"⚠️ Face Detection 빌드 실패: {e} — 눈 reveal 비활성")
            self._fd = None

        self.available = True

    def process(self, frame_bgr: np.ndarray) -> SilhouetteResult:
        """프레임 1회 추론. mediapipe는 RGB를 받으므로 색공간 변환 후 호출."""
        if not self.available or self._seg is None:
            return SilhouetteResult()

        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # 1) Selfie Segmentation → person_mask (uint8 0/255)
        seg_res = self._seg.process(rgb)
        seg_mask_prob = getattr(seg_res, "segmentation_mask", None)
        if seg_mask_prob is None:
            return SilhouetteResult()

        person_mask = np.where(seg_mask_prob > self._mask_threshold, 255, 0).astype(np.uint8)
        person_present = bool(person_mask.sum() > 0)

        # 2) Face Detection → eye/nose/mouth keypoints (픽셀 좌표)
        eye_points: List[Tuple[int, int]] = []
        nose_point: Optional[Tuple[int, int]] = None
        mouth_point: Optional[Tuple[int, int]] = None
        if self._fd is not None:
            fd_res = self._fd.process(rgb)
            detections = getattr(fd_res, "detections", None) or []
            if detections:
                h, w = frame_bgr.shape[:2]
                kps = detections[0].location_data.relative_keypoints
                # mediapipe face detection keypoint 순서:
                # 0=right eye, 1=left eye, 2=nose tip, 3=mouth, 4=right ear, 5=left ear
                def _px(idx):
                    if idx >= len(kps):
                        return None
                    kp = kps[idx]
                    px = int(round(kp.x * w))
                    py = int(round(kp.y * h))
                    if 0 <= px < w and 0 <= py < h:
                        return (px, py)
                    return None

                for idx in (0, 1):
                    p = _px(idx)
                    if p is not None:
                        eye_points.append(p)
                nose_point = _px(2)
                mouth_point = _px(3)

        detected = person_present and mouth_point is not None
        return SilhouetteResult(
            person_mask=person_mask,
            eye_points=eye_points,
            nose_point=nose_point,
            mouth_point=mouth_point,
            detected=detected,
        )

    def close(self) -> None:
        """리소스 해제."""
        if self._seg is not None and hasattr(self._seg, "close"):
            self._seg.close()
        if self._fd is not None and hasattr(self._fd, "close"):
            self._fd.close()
        self._seg = None
        self._fd = None
        self.available = False
