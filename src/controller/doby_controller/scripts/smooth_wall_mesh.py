#!/usr/bin/env python3
"""smooth_wall_mesh.py — STL wall mesh 의 vertex laplacian smoothing.

mapv5 의 walls_high.stl / walls_low.stl 같은 wall mesh 의
외곽 라인을 부드럽게 다듬는다. Taubin 필터 (λ + μ) 적용으로 shrinking 방지.

원본 STL 은 건드리지 않고 _smooth.stl 별 파일로 저장. model.sdf 의 mesh uri 만
변경하면 가역적 토글.

의존성: numpy + scipy.sparse (시스템 apt python3-numpy + scipy)

사용:
    python3 scripts/smooth_wall_mesh.py \
        src/moca_gazebo/models/mapv5/meshes/walls_high.stl \
        --output src/moca_gazebo/models/mapv5/meshes/walls_high_smooth.stl \
        --iter 10 --lambda-val 0.5 --mu -0.53
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import lil_matrix, csr_matrix


def read_binary_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Binary STL → (vertices [V,3] unique, faces [F,3] indexed)."""
    with open(path, "rb") as f:
        f.read(80)  # header
        n_tri = struct.unpack("<I", f.read(4))[0]
        raw = np.zeros((n_tri, 3, 3), dtype=np.float64)
        for i in range(n_tri):
            f.read(12)  # normal (ignored, will recompute)
            for v in range(3):
                raw[i, v] = struct.unpack("<fff", f.read(12))
            f.read(2)  # attr byte count

    # Dedupe vertices (STL 은 vertex 중복 — face index 만들기 위해 unique)
    flat = raw.reshape(-1, 3)
    # round to avoid float jitter when comparing
    key = np.round(flat * 1e6).astype(np.int64)
    _, unique_idx, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    vertices = flat[unique_idx]
    faces = inverse.reshape(n_tri, 3)
    return vertices, faces


def build_adjacency(faces: np.ndarray, n_verts: int) -> csr_matrix:
    """Vertex-vertex adjacency (1 if connected via edge, 0 otherwise)."""
    A = lil_matrix((n_verts, n_verts), dtype=np.float64)
    for tri in faces:
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            A[a, b] = 1
            A[b, a] = 1
    return A.tocsr()


def laplacian_step(verts: np.ndarray, A: csr_matrix, factor: float) -> np.ndarray:
    """1 step Laplacian smoothing: v ← v + factor * (mean(neighbors) - v)."""
    degree = np.asarray(A.sum(axis=1)).flatten()
    degree[degree == 0] = 1.0  # avoid div0
    neighbor_sum = A @ verts
    neighbor_mean = neighbor_sum / degree[:, None]
    return verts + factor * (neighbor_mean - verts)


def taubin_smooth(
    verts: np.ndarray,
    faces: np.ndarray,
    n_iter: int,
    lam: float,
    mu: float,
    lock_z: bool = True,
) -> np.ndarray:
    """Taubin λ|μ 필터 — λ smooth (수축) → μ inverse smooth (확장).
    Net shrinking 방지.

    lock_z=True 면 Z 좌표 고정 (벽 mesh 의 top/bottom 평면 보존, XY 외곽 라인만 smooth).
    """
    A = build_adjacency(faces, len(verts))
    v = verts.copy()
    z_orig = v[:, 2].copy() if lock_z else None
    for _ in range(n_iter):
        v = laplacian_step(v, A, lam)
        if lock_z:
            v[:, 2] = z_orig
        v = laplacian_step(v, A, mu)
        if lock_z:
            v[:, 2] = z_orig
    return v


def write_binary_stl(path: Path, verts: np.ndarray, faces: np.ndarray) -> None:
    """vertices + faces → binary STL. Normal 은 face 마다 재계산."""
    tris = verts[faces]  # [F, 3, 3]
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    n = np.cross(v1 - v0, v2 - v0)
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    n = (n / norm).astype(np.float32)

    with open(path, "wb") as f:
        f.write(b"moca smooth mesh".ljust(80, b" "))
        f.write(struct.pack("<I", len(faces)))
        for i in range(len(faces)):
            f.write(n[i].tobytes())
            for v in tris[i]:
                f.write(v.astype(np.float32).tobytes())
            f.write(b"\x00\x00")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path, help="원본 STL")
    p.add_argument("--output", "-o", type=Path, required=True, help="smoothed STL 출력")
    p.add_argument("--iter", "-n", type=int, default=10, help="Taubin iter (default 10)")
    p.add_argument("--lambda-val", type=float, default=0.5,
                   help="positive smoothing factor (default 0.5)")
    p.add_argument("--mu", type=float, default=-0.53,
                   help="negative anti-shrink factor (default -0.53 — Taubin paper)")
    p.add_argument("--no-lock-z", action="store_true",
                   help="Z 좌표도 smooth (기본은 lock — top/bottom 평면 보존)")
    args = p.parse_args()

    if not args.input.is_file():
        print(f"ERR: input not found: {args.input}", file=sys.stderr)
        return 1

    print(f"loading {args.input} ...")
    verts, faces = read_binary_stl(args.input)
    print(f"  vertices: {len(verts)}, faces: {len(faces)}")
    bb = verts.max(axis=0) - verts.min(axis=0)
    print(f"  bbox: {bb[0]:.2f} x {bb[1]:.2f} x {bb[2]:.2f} m")

    print(f"taubin smoothing — iter={args.iter}, lambda={args.lambda_val}, mu={args.mu}, lock_z={not args.no_lock_z}")
    new_verts = taubin_smooth(verts, faces, args.iter, args.lambda_val, args.mu, lock_z=not args.no_lock_z)

    bb_after = new_verts.max(axis=0) - new_verts.min(axis=0)
    print(f"  after bbox: {bb_after[0]:.2f} x {bb_after[1]:.2f} x {bb_after[2]:.2f} m")
    delta = np.linalg.norm(new_verts - verts, axis=1)
    print(f"  vertex displacement — mean={delta.mean()*100:.2f} cm, max={delta.max()*100:.2f} cm")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_binary_stl(args.output, new_verts, faces)
    print(f"written → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
