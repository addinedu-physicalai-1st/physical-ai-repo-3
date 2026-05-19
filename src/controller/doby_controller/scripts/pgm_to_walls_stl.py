#!/usr/bin/env python3
"""Convert a ROS occupancy-grid .pgm into extruded wall STL(s) for Gazebo.

Each occupied (black) pixel becomes a `resolution`-sized box on the floor,
extruded to `wall_height`. With `--regions <json>`, named pixel-aligned
rectangles can override the height per pixel:

  {
    "skip":    [{"name": "yellow_table", "rmin": 95, "rmax": 110,
                                            "cmin": 343, "cmax": 386}],
    "low":     [{"name": "alcove",      "rmin": 0,  "rmax": 95,
                                            "cmin": 300, "cmax": 391,
                                            "height": 0.9}]
  }

Pixels inside any `skip` rect are not extruded at all (use this where a
furniture model will replace the obstacle in the world). Pixels inside any
`low` rect are extruded to that rect's `height` instead of the default
`--wall-height`. `skip` wins over `low`. Rectangles can overlap; the
behavior is: for each pixel, the resolved height is the min of all matching
regions (so a `low` 0.9 m on top of the default 2.0 m yields 0.9 m).

Outputs binary STL (no external deps required).
"""
import argparse
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image


def box_triangles(x0, y0, x1, y1, z0, z1):
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def write_binary_stl(path: Path, triangles):
    with open(path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(triangles)))
        for tri in triangles:
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            ln = (nx * nx + ny * ny + nz * nz) ** 0.5
            if ln > 0:
                nx, ny, nz = nx / ln, ny / ln, nz / ln
            f.write(struct.pack("<3f", nx, ny, nz))
            f.write(struct.pack("<3f", ax, ay, az))
            f.write(struct.pack("<3f", bx, by, bz))
            f.write(struct.pack("<3f", cx, cy, cz))
            f.write(struct.pack("<H", 0))


def merge_runs(occ_row):
    runs = []
    i, n = 0, len(occ_row)
    while i < n:
        if occ_row[i]:
            j = i
            while j < n and occ_row[j]:
                j += 1
            runs.append((i, j - i))
            i = j
        else:
            i += 1
    return runs


def build_height_map(H, W, default_h, regions):
    """Per-pixel target wall height; -1 means "skip (no wall)"."""
    heights = np.full((H, W), default_h, dtype=np.float32)
    for r in regions.get("low", []):
        rmin = max(0, r["rmin"]); rmax = min(H - 1, r["rmax"])
        cmin = max(0, r["cmin"]); cmax = min(W - 1, r["cmax"])
        h = float(r["height"])
        # min so overlapping low rects pick the lowest
        heights[rmin:rmax + 1, cmin:cmax + 1] = np.minimum(
            heights[rmin:rmax + 1, cmin:cmax + 1], h)
    skip_mask = np.zeros((H, W), dtype=bool)
    for r in regions.get("skip", []):
        rmin = max(0, r["rmin"]); rmax = min(H - 1, r["rmax"])
        cmin = max(0, r["cmin"]); cmax = min(W - 1, r["cmax"])
        skip_mask[rmin:rmax + 1, cmin:cmax + 1] = True
    return heights, skip_mask


def pgm_to_stl(pgm_path, stl_path, resolution, wall_height, occ_thresh,
               regions):
    img = np.array(Image.open(pgm_path))
    H, W = img.shape
    occupied = img < occ_thresh
    print(f"  source: {pgm_path}  ({W}x{H}, {occupied.sum()} occupied)")
    heights, skip_mask = build_height_map(H, W, wall_height, regions)

    triangles = []
    extruded = 0
    for r in range(H):
        # Group consecutive pixels with the same effective height into runs
        # (skip pixels break runs).
        c = 0
        while c < W:
            if not occupied[r, c] or skip_mask[r, c]:
                c += 1
                continue
            h = float(heights[r, c])
            # extend run: same occupied + same height + not skipped
            j = c
            while (j < W and occupied[r, j] and not skip_mask[r, j]
                   and float(heights[r, j]) == h):
                j += 1
            world_row = H - 1 - r
            x0 = c * resolution
            x1 = j * resolution
            y0 = world_row * resolution
            y1 = (world_row + 1) * resolution
            triangles.extend(box_triangles(x0, y0, x1, y1, 0.0, h))
            extruded += (j - c)
            c = j

    skipped = int(skip_mask[occupied].sum())
    print(f"  pixels: extruded={extruded}, skipped={skipped} "
          f"(skip-mask covers {int(skip_mask.sum())} px)")
    print(f"  triangles: {len(triangles):,}")
    write_binary_stl(stl_path, triangles)
    print(f"  wrote: {stl_path}  ({stl_path.stat().st_size / 1024:.1f} KiB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pgm", type=Path)
    ap.add_argument("stl", type=Path)
    ap.add_argument("--resolution", type=float, default=0.05)
    ap.add_argument("--wall-height", type=float, default=2.0)
    ap.add_argument("--occ-thresh", type=int, default=50)
    ap.add_argument("--regions", type=Path, default=None,
                    help="JSON file with 'skip' and 'low' rectangle lists")
    args = ap.parse_args()
    regions = {"skip": [], "low": []}
    if args.regions is not None:
        regions = json.loads(args.regions.read_text())
    args.stl.parent.mkdir(parents=True, exist_ok=True)
    pgm_to_stl(args.pgm, args.stl, args.resolution, args.wall_height,
               args.occ_thresh, regions)


if __name__ == "__main__":
    main()
