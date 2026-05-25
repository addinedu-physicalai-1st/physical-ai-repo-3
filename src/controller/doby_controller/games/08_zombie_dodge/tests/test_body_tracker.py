"""body_tracker — PersonMask 추출 단위 테스트."""
import numpy as np
import pytest

from body_tracker import PersonMask, compute_person_mask, DEFAULT_MIN_PIXEL_RATIO


def _disk(h, w, cx, cy, r):
    yy, xx = np.ogrid[:h, :w]
    return ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r).astype(np.uint8)


def test_compute_person_mask_valid_returns_personmask():
    raw = _disk(720, 1280, 640, 360, 200)
    person = compute_person_mask(raw)
    assert person is not None
    assert person.mask.shape == (720, 1280)
    x1, y1, x2, y2 = person.bbox
    assert x1 < 640 < x2
    assert y1 < 360 < y2


def test_compute_person_mask_too_small_returns_none():
    raw = _disk(720, 1280, 640, 360, 30)
    assert compute_person_mask(raw) is None


def test_compute_person_mask_empty_returns_none():
    raw = np.zeros((720, 1280), dtype=np.uint8)
    assert compute_person_mask(raw) is None


def test_compute_person_mask_none_input_returns_none():
    assert compute_person_mask(None) is None


def test_default_min_pixel_ratio_is_two_percent():
    assert DEFAULT_MIN_PIXEL_RATIO == pytest.approx(0.02)


def test_person_mask_center_inside_disk():
    raw = _disk(720, 1280, 640, 360, 200)
    person = compute_person_mask(raw)
    cx, cy = person.center
    assert abs(cx - 640) < 50
    assert abs(cy - 360) < 50
