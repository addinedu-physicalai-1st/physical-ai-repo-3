import numpy as np
import pytest

from dobi_npc_identity.customer_registry import CustomerRegistry, cosine_similarity


def _emb(*vals, dim=512):
    """앞쪽 값만 지정하고 나머지는 0 으로 채운 dim-차원 임베딩."""
    v = np.zeros(dim, dtype=np.float32)
    v[:len(vals)] = vals
    return v


def test_cosine_similarity_identical():
    v = _emb(1.0, 2.0, 3.0)
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    assert cosine_similarity(_emb(1.0, 0.0), _emb(0.0, 1.0)) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    # 0 벡터 → division-by-zero 없이 0.0
    assert cosine_similarity(_emb(0.0), _emb(1.0, 0.0)) == 0.0


def test_new_face_gets_new_customer_id():
    reg = CustomerRegistry()
    cid, conf = reg.resolve(track_id=1, embedding=_emb(1.0, 0.0))
    assert cid != ''
    assert reg.customer_count() == 1


def test_same_face_new_track_after_release_is_reidentified():
    # P0 핵심: track 이 끊겼다 재등장해도 같은 customer_id
    reg = CustomerRegistry()
    cid1, _ = reg.resolve(track_id=1, embedding=_emb(1.0, 0.0))
    reg.release_track(1)
    cid2, conf = reg.resolve(track_id=2, embedding=_emb(1.0, 0.0))
    assert cid2 == cid1
    assert reg.customer_count() == 1
    assert conf >= 0.5


def test_different_faces_get_different_customer_ids():
    reg = CustomerRegistry()
    cid1, _ = reg.resolve(track_id=1, embedding=_emb(1.0, 0.0))
    cid2, _ = reg.resolve(track_id=2, embedding=_emb(0.0, 1.0))  # 직교 → sim 0
    assert cid1 != cid2
    assert reg.customer_count() == 2


def test_bound_track_returns_cached_id_without_rematch():
    # track 이 살아있는 동안엔 임베딩이 달라져도 customer_id 고정 (churn 흡수)
    reg = CustomerRegistry()
    cid1, _ = reg.resolve(track_id=1, embedding=_emb(1.0, 0.0))
    cid_again, conf = reg.resolve(track_id=1, embedding=_emb(0.0, 1.0))
    assert cid_again == cid1
    assert conf == 1.0


def test_resolve_no_face_returns_bound_id_or_none():
    reg = CustomerRegistry()
    cid1, _ = reg.resolve(track_id=1, embedding=_emb(1.0, 0.0))
    assert reg.resolve_no_face(1) == cid1
    assert reg.resolve_no_face(99) is None


def test_match_threshold_boundary():
    reg = CustomerRegistry(match_threshold=0.5)
    cid1, _ = reg.resolve(track_id=1, embedding=_emb(1.0, 0.0))
    reg.release_track(1)
    # sim 0.6 (>= 0.5) → 동일 손님으로 매칭
    cid_above, _ = reg.resolve(track_id=2, embedding=_emb(0.6, 0.8))
    assert cid_above == cid1
    reg.release_track(2)
    # sim 0.4 (< 0.5) → 신규 손님
    cid_below, _ = reg.resolve(track_id=3, embedding=_emb(0.4, 0.9165))
    assert cid_below != cid1
    assert reg.customer_count() == 2
