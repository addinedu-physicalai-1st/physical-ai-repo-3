"""dobi_dock 테이블 엣지 퍼셉션 -- 순수 numpy, ROS 무의존.

오프라인 프로토타입(/tmp/depth_probe/{probe,roi_test}.py)에서 이식 + 적대적 리뷰 반영.
입력 점들은 이미 BASE/로봇 프레임으로 표현돼 있다고 가정:
    x = 전방, y = 좌측, z = 상방   (REP-103, 단위 m).
optical->base 변환(고정 도킹포즈 카메라 extrinsic, 1회 캘리브)은 ROS 노드 담당.

파이프라인:
  1. ROI 크롭 (전방/좌/상 범위).
  2. RANSAC 지배 평면 -> 수평성 검사 (테이블 vs 벽 REJECT) + (선택) 높이범위 검사.
  3. 근측 엣지: 한 축으로 bin, 각 bin 에서 다른 축 근측 슬라이버 -> 2D 직선(SVD) 피팅.
  4. 기준점(로봇 좌측면 y=+0.27)에서 엣지까지 부호있는 횡오차 + 엣지 각도.

부호 규약 (도킹 컨트롤러가 의존하므로 결정성 필수):
  - 엣지 법선은 docking_side 에 따라 결정적으로 향함(좌측 도킹 -> -y, 로봇 쪽).
  - lateral_error = 법선·(ref - through). 좌측 도킹에서 양수 = 엣지가 로봇 좌측면(y=0.27)
    보다 더 바깥(+y) = 갭이 큼. 0 에 가깝게(목표 갭) 만드는 게 정렬.
  - angle_deg = 엣지 방향 vs base x. 평행 밀착 -> ~0 도.

좌측 도킹 기하(docking_side='left'): 테이블 좌측(+y), 근측 엣지는 x 로 뻗음
(bin=x, near=min y). 'right'/'front' 프리셋도 제공.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

import numpy as np


class Plane(NamedTuple):
    normal: np.ndarray    # 단위벡터 (3,)
    offset: float         # 평면식 normal . x + d = 0 의 d
    inliers: np.ndarray   # 입력 점에 대한 bool 마스크


class EdgeFit(NamedTuple):
    through: np.ndarray    # (2,) 엣지 직선 위의 한 점 (base xy)
    direction: np.ndarray  # (2,) 단위벡터, 엣지 진행방향
    normal: np.ndarray     # (2,) 단위벡터, 엣지에 수직(부호 결정적)
    n_points: int


class TableEdgeResult(NamedTuple):
    table_found: bool
    horizontal: bool
    table_height: Optional[float]   # inlier 의 base z 중앙값
    n_inliers: int
    inlier_ratio: float             # ROI 점 대비 평면 inlier 비율(컨피던스)
    edge: Optional[EdgeFit]
    lateral_error: Optional[float]  # 부호있는 거리 ref_xy -> 엣지 직선 [m]
    angle_deg: Optional[float]      # 엣지 방향 vs base x, (-90, 90]


# docking_side 프리셋: (ref_xy, bin_axis, near_axis, take, prefer_normal)
_SIDE_PRESETS = {
    # 좌측 도킹: 테이블 +y, 엣지 x방향, 법선은 로봇 쪽(-y)
    'left':  ((0.0, 0.27), 0, 1, 'min', (0.0, -1.0)),
    # 우측 도킹: 테이블 -y, 엣지 x방향, 법선은 로봇 쪽(+y)
    'right': ((0.0, -0.27), 0, 1, 'max', (0.0, 1.0)),
    # 전방(프로토타입식): 테이블 +x, 엣지 y방향, 법선은 로봇 쪽(-x)
    'front': ((0.0, 0.0), 1, 0, 'min', (-1.0, 0.0)),
}


def ransac_plane(pts, thresh=0.018, iters=400, seed=0):
    """RANSAC + 최소제곱(SVD) 재추정으로 지배 평면 추출. 순수 numpy.

    퇴화입력(점 3개 미만, 유효 평면 미발견)에도 예외 없이 빈 inlier 평면 반환.
    """
    n = len(pts)
    if n < 3:                                   # 평면 정의 불가
        return Plane(np.array([0.0, 0.0, 1.0]), 0.0,
                     np.zeros(n, dtype=bool))
    rng = np.random.default_rng(seed)
    best_mask, best_cnt = None, -1
    for _ in range(iters):
        idx = rng.choice(n, 3, replace=False)
        p0, p1, p2 = pts[idx]
        nv = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(nv)
        if nn < 1e-9:                           # 거의 일직선 3점 -> 스킵
            continue
        nv = nv / nn
        d = -nv.dot(p0)
        mask = np.abs(pts.dot(nv) + d) < thresh
        c = int(mask.sum())
        if c > best_cnt:
            best_cnt, best_mask = c, mask
    if best_mask is None or best_cnt < 3:       # 유효 평면 미발견
        return Plane(np.array([0.0, 0.0, 1.0]), 0.0,
                     np.zeros(n, dtype=bool))
    # 최선 inlier 로 최소제곱 재추정 (법선 = 최소 특이값 방향)
    inl = pts[best_mask]
    centroid = inl.mean(axis=0)
    _, _, vh = np.linalg.svd(inl - centroid, full_matrices=False)
    nv = vh[2]
    nv = nv / np.linalg.norm(nv)
    if nv[2] < 0:                               # 법선 부호 통일(z+ 향)
        nv = -nv
    d = -nv.dot(centroid)
    mask = np.abs(pts.dot(nv) + d) < thresh
    return Plane(nv, float(d), mask)


def is_horizontal(normal, tol=0.9):
    """|normal . z| > tol 이면 수평면(상판/바닥). 벽은 REJECT."""
    return abs(float(normal[2])) > tol


def crop_roi(pts, x=(-1.0, 1.5), y=(-1.2, 1.2), z=(0.5, 0.95)):
    """base 프레임 박스 ROI 크롭. (크롭된 점, 마스크) 반환."""
    m = ((pts[:, 0] > x[0]) & (pts[:, 0] < x[1]) &
         (pts[:, 1] > y[0]) & (pts[:, 1] < y[1]) &
         (pts[:, 2] > z[0]) & (pts[:, 2] < z[1]))
    return pts[m], m


def near_edge_points(xy, bin_axis=0, near_axis=1, take='min',
                     nbins=30, pct=5.0, band=0.01, min_pts=5):
    """bin_axis 각 bin 에서 near_axis 의 근측 슬라이버를 모은다. Nx2 반환."""
    b = xy[:, bin_axis]
    if len(b) == 0:
        return np.empty((0, 2))
    edges = np.linspace(b.min(), b.max(), nbins + 1)
    out = []
    for i in range(nbins):
        m = (b >= edges[i]) & (b < edges[i + 1])
        if int(m.sum()) < min_pts:              # 점 부족 bin 스킵
            continue
        vi = xy[m, near_axis]
        if take == 'min':
            thr = np.percentile(vi, pct)
            sel = m & (xy[:, near_axis] <= thr + band)
        else:
            thr = np.percentile(vi, 100.0 - pct)
            sel = m & (xy[:, near_axis] >= thr - band)
        if int(sel.sum()) == 0:
            continue
        out.append([xy[sel, 0].mean(), xy[sel, 1].mean()])
    return np.array(out) if out else np.empty((0, 2))


def fit_line_2d(pts2d, prefer_normal=None, min_pts=3, max_aspect=None):
    """SVD total-least-squares 직선 피팅. EdgeFit 또는 None.

    prefer_normal: 주어지면 법선이 그 방향을 향하도록 부호 결정(도킹 부호 안정화).
    min_pts: 최소 점 개수(미만이면 None).
    max_aspect: sv[1]/sv[0] 가 이 값보다 크면(점들이 직선 아닌 산포) None. (None=비활성)
    """
    if len(pts2d) < max(2, min_pts):
        return None
    c = pts2d.mean(axis=0)
    _, s, vh = np.linalg.svd(pts2d - c, full_matrices=False)
    if max_aspect is not None and s[0] > 1e-9 and (s[1] / s[0]) > max_aspect:
        return None                              # 너무 산포 -> 직선 아님
    direction = vh[0] / np.linalg.norm(vh[0])    # 최대 분산축 = 엣지 방향
    normal = vh[1] / np.linalg.norm(vh[1])       # 최소 분산축 = 법선
    if prefer_normal is not None:                # 법선 부호 결정성
        pn = np.asarray(prefer_normal, dtype=float)
        if normal.dot(pn) < 0:
            normal = -normal
    return EdgeFit(c, direction, normal, len(pts2d))


def signed_lateral_error(edge, ref_xy):
    """ref_xy 에서 엣지 직선까지 부호있는 수직거리 = normal·(ref - through).

    좌측 도킹(법선 -y, 로봇 쪽): 양수 = 엣지가 로봇 좌측면보다 더 바깥(+y) = 갭 큼.
    """
    ref = np.asarray(ref_xy, dtype=float)
    return float(edge.normal.dot(ref - edge.through))


def edge_angle_deg(edge):
    """엣지 방향의 base x(전방) 대비 각도, (-90, 90] 래핑(직선은 방향 무관)."""
    a = float(np.degrees(np.arctan2(edge.direction[1], edge.direction[0])))
    if a > 90.0:
        a -= 180.0
    elif a <= -90.0:
        a += 180.0
    return a


def analyze_table_edge(points_base, docking_side='left', roi=None,
                       ref_xy=None, bin_axis=None, near_axis=None, take=None,
                       prefer_normal=None, horiz_tol=0.9, thresh=0.018,
                       iters=400, seed=0, nbins=30, pct=5.0, band=0.01,
                       min_pts=5, min_roi_pts=50, table_z=None,
                       max_aspect=0.5):
    """base 프레임 점들에 대한 전체 파이프라인. 모듈 docstring 참조.

    docking_side('left'/'right'/'front') 가 ref_xy/bin/near/take/prefer_normal 의
    기본값을 정하고, 동명 인자를 명시하면 개별 override.
    table_z=(zmin,zmax) 주면 상판 높이범위 검사(바닥/엉뚱한 평면 REJECT).
    """
    fail = TableEdgeResult(False, False, None, 0, 0.0, None, None, None)

    pts = np.asarray(points_base, dtype=float)
    if pts.ndim != 2 or pts.shape[0] == 0:
        return fail
    finite = np.isfinite(pts).all(axis=1)       # NaN/Inf 정제
    pts = pts[finite]
    if len(pts) < min_roi_pts:
        return fail

    preset = _SIDE_PRESETS.get(docking_side, _SIDE_PRESETS['left'])
    if ref_xy is None:
        ref_xy = preset[0]
    if bin_axis is None:
        bin_axis = preset[1]
    if near_axis is None:
        near_axis = preset[2]
    if take is None:
        take = preset[3]
    if prefer_normal is None:
        prefer_normal = preset[4]

    if roi is None:
        roi = dict(x=(-1.0, 1.5), y=(-1.2, 1.2), z=(0.5, 0.95))
    crop, _ = crop_roi(pts, **roi)
    if len(crop) < min_roi_pts:                 # ROI 점 부족
        return fail

    plane = ransac_plane(crop, thresh=thresh, iters=iters, seed=seed)
    top = crop[plane.inliers]
    n_in = int(len(top))
    ratio = float(n_in / max(1, len(crop)))
    if n_in < min_roi_pts:                       # 평면 inlier 부족
        return TableEdgeResult(False, False, None, n_in, ratio, None, None, None)
    height = float(np.median(top[:, 2]))
    horiz = is_horizontal(plane.normal, horiz_tol)
    if table_z is not None and not (table_z[0] <= height <= table_z[1]):
        horiz = False                            # 높이범위 밖 -> 상판 아님
    if not horiz:                                # 벽/바닥 등 REJECT
        return TableEdgeResult(False, False, height, n_in, ratio, None, None, None)

    edge = fit_line_2d(
        near_edge_points(top[:, :2], bin_axis, near_axis, take, nbins, pct, band, min_pts),
        prefer_normal=prefer_normal, min_pts=3, max_aspect=max_aspect)
    if edge is None:                             # 엣지 피팅 실패
        return TableEdgeResult(True, True, height, n_in, ratio, None, None, None)
    lat = signed_lateral_error(edge, ref_xy)
    ang = edge_angle_deg(edge)
    return TableEdgeResult(True, True, height, n_in, ratio, edge, lat, ang)
