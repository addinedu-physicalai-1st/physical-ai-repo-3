"""face_embedder -- insightface(ArcFace) 얼굴 임베딩 추출 래퍼.

insightface 의존성을 이 파일 한 곳에 격리 (customer_registry 는 순수 로직 유지).
"""
import numpy as np


class FaceEmbedder:
    """BGR 이미지/ROI 에서 512-d L2-정규화 얼굴 임베딩 추출."""

    def __init__(self, det_size: int = 640):
        from insightface.app import FaceAnalysis
        self._app = FaceAnalysis(
            name='buffalo_l',
            providers=['CPUExecutionProvider'],
            allowed_modules=['detection', 'recognition'],
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))

    def embed_largest_face(self, bgr_image: np.ndarray) -> 'np.ndarray | None':
        """이미지에서 가장 큰 얼굴의 정규화 임베딩(512-d). 얼굴 없으면 None."""
        faces = self._app.get(bgr_image)
        if not faces:
            return None
        largest = max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )
        return largest.normed_embedding.astype(np.float32)

    def embed_in_roi(self, bgr_image: np.ndarray, bbox) -> 'np.ndarray | None':
        """bbox=[x1,y1,x2,y2] ROI 안에서 얼굴 임베딩 추출. ROI 무효/얼굴없음 -> None."""
        x1, y1, x2, y2 = (int(v) for v in bbox)
        h, w = bgr_image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return self.embed_largest_face(bgr_image[y1:y2, x1:x2])
