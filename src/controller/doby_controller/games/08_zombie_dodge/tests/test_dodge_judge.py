"""dodge_judge — mask × circle 충돌 단위 테스트."""
import numpy as np
import pytest

from body_tracker import PersonMask, compute_person_mask
from dodge_judge import mask_circle_collide, evaluate_frame, FrameJudgement
from zombie import make_zombie, KIND_NORMAL


def _person(h, w, cx, cy, r):
    yy, xx = np.ogrid[:h, :w]
    raw = ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r).astype(np.uint8)
    return compute_person_mask(raw)


class TestMaskCircle:
    def test_circle_inside_collides(self):
        p = _person(720, 1280, 640, 360, 200)
        assert mask_circle_collide(p.mask, 640, 360, 40) is True

    def test_circle_outside_passes(self):
        p = _person(720, 1280, 640, 360, 200)
        assert mask_circle_collide(p.mask, 100, 100, 40) is False

    def test_circle_partial_edge_below_threshold_passes(self):
        p = _person(720, 1280, 640, 360, 200)
        # 원이 마스크 경계 살짝 바깥 → overlap 거의 없음
        assert mask_circle_collide(p.mask, 640 + 235, 360, 40, overlap_ratio=0.15) is False

    def test_mask_none_returns_false(self):
        assert mask_circle_collide(None, 100, 100, 40) is False

    def test_zero_radius_returns_false(self):
        p = _person(720, 1280, 640, 360, 200)
        assert mask_circle_collide(p.mask, 640, 360, 0) is False

    def test_circle_fully_off_screen_returns_false(self):
        p = _person(720, 1280, 640, 360, 200)
        assert mask_circle_collide(p.mask, -200, -200, 40) is False


class TestEvaluateFrame:
    def test_none_person_skips_collision(self):
        z = make_zombie(x=640, y=360, vy=300, kind=KIND_NORMAL)
        j = evaluate_frame([z], person=None, dodge_y_threshold=700)
        assert j.collisions == []
        assert z.dodged is False

    def test_collision_marks_dodged(self):
        p = _person(720, 1280, 640, 360, 200)
        z = make_zombie(x=640, y=360, vy=300, kind=KIND_NORMAL)
        j = evaluate_frame([z], person=p, dodge_y_threshold=700)
        assert z in j.collisions
        assert z.dodged is True

    def test_pass_below_threshold(self):
        p = _person(720, 1280, 640, 360, 200)
        z = make_zombie(x=100, y=750, vy=300, kind=KIND_NORMAL)
        j = evaluate_frame([z], person=p, dodge_y_threshold=700)
        assert z in j.passes
        assert z.passed is True

    def test_already_marked_zombie_ignored(self):
        p = _person(720, 1280, 640, 360, 200)
        z = make_zombie(x=640, y=360, vy=300, kind=KIND_NORMAL)
        z.dodged = True
        j = evaluate_frame([z], person=p, dodge_y_threshold=700)
        assert j.collisions == []
        assert j.passes == []
