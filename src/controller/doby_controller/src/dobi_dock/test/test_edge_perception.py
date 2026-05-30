"""edge_perception 단위테스트 -- 합성 포인트클라우드, 순수 numpy (HW/ROS 불요)."""
from __future__ import annotations

import numpy as np

from dobi_dock.edge_perception import (
    EdgeFit,
    analyze_table_edge,
    edge_angle_deg,
    fit_line_2d,
    is_horizontal,
    near_edge_points,
    ransac_plane,
)

ROI = dict(x=(-1, 1.5), y=(-1.2, 1.2), z=(0.5, 0.95))


def _table(z=0.7, x=(0.2, 1.0), y=(0.30, 1.0), n=4000, noise=0.002, seed=0):
    """base 프레임 수평 상판. 근측 엣지 = y 최소(= y[0]), 엣지는 x 로 뻗음."""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(x[0], x[1], n)
    ys = rng.uniform(y[0], y[1], n)
    zs = z + rng.normal(0.0, noise, n)
    return np.column_stack([xs, ys, zs])


def _wall(x0=0.6, y=(-0.5, 0.5), z=(0.0, 1.0), n=4000, noise=0.002, seed=1):
    """수직 벽 (법선 ~ x). 수평성 검사에서 REJECT 되어야 함."""
    rng = np.random.default_rng(seed)
    ys = rng.uniform(y[0], y[1], n)
    zs = rng.uniform(z[0], z[1], n)
    xs = x0 + rng.normal(0.0, noise, n)
    return np.column_stack([xs, ys, zs])


def test_ransac_recovers_horizontal_plane():
    pts = _table(z=0.7)
    pl = ransac_plane(pts, thresh=0.01, iters=200)
    assert abs(pl.normal[2]) > 0.99               # 법선 부호 통일(z+) + 수평
    assert pl.inliers.mean() > 0.9
    assert abs(np.median(pts[pl.inliers][:, 2]) - 0.7) < 0.01


def test_ransac_degenerate_no_exception():
    assert ransac_plane(np.zeros((0, 3))).inliers.sum() == 0          # 0점
    assert ransac_plane(np.array([[0., 0., 0.], [1., 0., 0.]])).inliers.sum() == 0  # 2점
    collinear = np.column_stack([np.linspace(0, 1, 50), np.zeros(50), np.zeros(50)])
    assert ransac_plane(collinear).inliers.sum() == 0                # 일직선


def test_is_horizontal():
    assert is_horizontal(np.array([0.0, 0.0, 1.0]))
    assert is_horizontal(np.array([0.05, -0.05, 0.997]))
    assert not is_horizontal(np.array([1.0, 0.0, 0.0]))


def test_edge_angle_wrapping():
    assert abs(edge_angle_deg(EdgeFit(np.zeros(2), np.array([1.0, 0.0]),
                                      np.array([0.0, 1.0]), 9))) < 1e-6
    assert abs(edge_angle_deg(EdgeFit(np.zeros(2), np.array([0.0, 1.0]),
                                      np.array([1.0, 0.0]), 9)) - 90.0) < 1e-6
    assert abs(edge_angle_deg(EdgeFit(np.zeros(2), np.array([0.0, -1.0]),
                                      np.array([1.0, 0.0]), 9)) - 90.0) < 1e-6


def test_fit_line_min_points_and_prefer_normal():
    pts = np.column_stack([np.linspace(0, 1, 10), np.full(10, 0.3)])  # x 로 뻗는 직선
    assert fit_line_2d(pts[:2]) is None              # 2점 < min_pts(3)
    f = fit_line_2d(pts, prefer_normal=(0.0, -1.0))
    assert abs(f.direction[0]) > 0.99                # 방향 ~ x
    assert f.normal[1] < 0                            # 법선 부호 -y 로 결정


def test_near_edge_runs_along_x_for_left_table():
    top = _table(z=0.7, x=(0.2, 1.0), y=(0.30, 1.0))[:, :2]
    ep = near_edge_points(top, bin_axis=0, near_axis=1, take='min')
    assert len(ep) >= 5
    assert 0.30 <= ep[:, 1].mean() <= 0.40
    f = fit_line_2d(ep, prefer_normal=(0.0, -1.0))
    assert abs(f.direction[0]) > 0.9
    assert abs(edge_angle_deg(f)) < 10.0


def test_analyze_left_side_table():
    pts = _table(z=0.7, x=(0.2, 1.0), y=(0.30, 1.0))
    r = analyze_table_edge(pts, docking_side='left', ref_xy=(0.6, 0.27), roi=ROI)
    assert r.table_found and r.horizontal
    assert abs(r.table_height - 0.7) < 0.01
    assert abs(r.angle_deg) < 10.0
    assert r.lateral_error is not None and abs(r.lateral_error) < 0.15
    assert r.inlier_ratio > 0.8


def test_lateral_error_sign_left_deterministic():
    # 좌측: 엣지(y~0.30)가 로봇측(0.27)보다 바깥 -> 양수, 시드 무관 결정성
    pts = _table(z=0.7, x=(0.2, 1.0), y=(0.30, 1.0))
    for seed in (0, 1, 7, 42):
        r = analyze_table_edge(pts, docking_side='left', ref_xy=(0.6, 0.27),
                               roi=ROI, seed=seed)
        assert r.lateral_error is not None and r.lateral_error > 0


def test_lateral_error_sign_right():
    rng = np.random.default_rng(3)
    xs = rng.uniform(0.2, 1.0, 4000)
    ys = rng.uniform(-1.0, -0.30, 4000)      # 테이블 우측(-y)
    zs = 0.7 + rng.normal(0, 0.002, 4000)
    pts = np.column_stack([xs, ys, zs])
    r = analyze_table_edge(pts, docking_side='right', ref_xy=(0.6, -0.27), roi=ROI)
    assert r.table_found and r.lateral_error is not None and r.lateral_error > 0


def test_analyze_rejects_wall():
    r = analyze_table_edge(_wall(), roi=ROI)
    assert not r.horizontal and not r.table_found


def test_analyze_table_z_reject():
    pts = _table(z=0.40, y=(0.30, 1.0))      # 수평이지만 낮은 면
    r = analyze_table_edge(pts, docking_side='left',
                           roi=dict(x=(-1, 1.5), y=(-1.2, 1.2), z=(0.2, 0.95)),
                           table_z=(0.65, 0.80))
    assert not r.table_found


def test_analyze_nan_graceful():
    pts = _table(z=0.7, y=(0.30, 1.0))
    pts[::50] = np.nan                        # 일부 NaN 주입
    r = analyze_table_edge(pts, docking_side='left', roi=ROI)
    assert r.table_found                      # NaN 정제 후 정상


def test_analyze_empty_roi_graceful():
    far = _table(z=0.7) + np.array([10.0, 10.0, 10.0])
    assert not analyze_table_edge(far).table_found
