"""customer_registry -- 얼굴 임베딩 기반 영속 customer_id 부여 + track 바인딩.

ROS / insightface 무의존 -- 순수 로직. 단위 테스트 대상.
"""
import uuid

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """두 임베딩의 코사인 유사도. 0 벡터 입력 시 0.0 (division-by-zero 회피)."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class CustomerRegistry:
    """track_id + 얼굴 임베딩 -> 영속 customer_id.

    - track 이 살아있는 동안: 바인딩 캐시 -> customer_id 고정 (track_id churn 흡수).
    - track 소실 후 재등장: 얼굴 임베딩 재매칭 -> 같은 사람이면 같은 customer_id.
    """

    def __init__(self, match_threshold: float = 0.5):
        self.match_threshold = match_threshold
        self._customers: dict[str, np.ndarray] = {}   # customer_id -> 대표 임베딩
        self._track_binding: dict[int, str] = {}      # track_id -> customer_id

    def resolve(self, track_id: int, embedding: np.ndarray) -> tuple[str, float]:
        """track_id + 임베딩 -> (customer_id, confidence).

        track_id 가 이미 바인딩돼 있으면 캐시 반환(재매칭 X, conf=1.0).
        아니면 registry 매칭: best >= threshold -> 재사용, 미만 -> 신규 customer.
        """
        bound = self._track_binding.get(track_id)
        if bound is not None:
            return bound, 1.0

        best_id, best_sim = self._best_match(embedding)
        if best_id is not None and best_sim >= self.match_threshold:
            self._track_binding[track_id] = best_id
            return best_id, best_sim

        cid = uuid.uuid4().hex[:12]
        self._customers[cid] = embedding.astype(np.float32).copy()
        self._track_binding[track_id] = cid
        return cid, 1.0

    def resolve_no_face(self, track_id: int) -> 'str | None':
        """track 은 있으나 얼굴 임베딩이 없을 때 -- 기존 바인딩만 반환."""
        return self._track_binding.get(track_id)

    def release_track(self, track_id: int) -> None:
        """track 소실 시 track->customer 바인딩 제거. customer 는 registry 에 유지."""
        self._track_binding.pop(track_id, None)

    def customer_count(self) -> int:
        return len(self._customers)

    def _best_match(self, embedding: np.ndarray) -> 'tuple[str | None, float]':
        best_id: 'str | None' = None
        best_sim = -1.0
        for cid, emb in self._customers.items():
            sim = cosine_similarity(embedding, emb)
            if sim > best_sim:
                best_id, best_sim = cid, sim
        return best_id, best_sim
