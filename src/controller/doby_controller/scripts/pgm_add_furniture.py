#!/usr/bin/env python3
"""Add Gazebo furniture occupancy to existing PGM map for AMCL scan match.

Vic Pinky LiDAR mount = base_link + 0.15m (lidar_mount 0.12 + laser_link 0.03).
가구별 매칭 footprint (LiDAR 0.15m 닿는 부분):
  - bar_counter base 1.16×0.56 (top 0.32m height, leg 도 닿음)
  - kiosk base 0.5×0.4 (base 0.08m + pole 0~42cm 모두 LiDAR 닿음)
  - cafe_table leg cluster 0.20×0.20 (top 0.37m 안 닿음, leg 만 0.04×0.04 × 4)
  - banner base 0.4×1.0 (panel 79cm 도 닿음)
  - floor_lamp base 0.4×0.4 (cylinder r=0.2)
  - bonsai_tree pot 0.3×0.3 (cylinder r=0.15)
  - OpenARM skip — z=0.89 (bar_counter 위) → LiDAR 안 닿음

Coordinate source: src/moca_gazebo/worlds/mapv5_moca.world (SoT, 사용자 picker 검증).

Usage:
  python3 scripts/pgm_add_furniture.py \\
      --in  maps/mapv5_mocamap.pgm \\
      --out maps/mapv5_mocamap.pgm \\
      --origin -51.32 -6.624 --resolution 0.05

Idempotent: 같은 PGM 에 다시 실행해도 새 픽셀 안 늘림 (이미 occupied).
"""
import argparse
import math

import numpy as np
from PIL import Image, ImageDraw


# (name, world_x, world_y, yaw_rad, sx, sy)
# sx = local-x size before yaw rotation, sy = local-y size
FURNITURE = [
    # 큰 가구 (scan 영향 큼)
    ("bar_counter", -36.070, 2.793,  3.142, 1.16, 0.56),
    ("kiosk",       -35.520, 3.409, -1.571, 0.50, 0.40),
    # cafe_table — top 0.37m LiDAR 0.15m 안 닿음. leg 4개 (0.04×0.04) 만
    # cluster 0.20×0.20 (leg span ≈ 0.6, 그러나 가구 보수 영역만)
    ("T01", -36.337,  0.526, 0.0, 0.20, 0.20),
    ("T02", -41.037,  0.243, 0.0, 0.20, 0.20),
    ("T03", -41.037, -0.574, 0.0, 0.20, 0.20),
    ("T04", -44.903,  0.243, 0.0, 0.20, 0.20),
    ("T05", -44.903, -0.507, 0.0, 0.20, 0.20),
    # banner — base 0.4×1.0 (panel 도 닿지만 폭 같음)
    ("B01", -38.053, 3.959, -1.571, 0.40, 1.00),
    ("B02", -35.787, 3.943, -1.571, 0.40, 1.00),
    ("B03", -41.353, 2.759, -1.571, 0.40, 1.00),
    ("B04", -44.387, 2.776, -1.571, 0.40, 1.00),
    # floor_lamp — cylinder r=0.2 → 0.4×0.4 box
    ("L01", -35.300,  0.526,  0.000, 0.40, 0.40),
    ("L02", -40.103,  2.726,  3.142, 0.40, 0.40),
    ("L03", -42.937,  0.376,  3.142, 0.40, 0.40),
    # bonsai_tree — pot r=0.15 → 0.3×0.3 box
    ("P01", -39.387,  2.743, 3.142, 0.30, 0.30),
    ("P02", -46.237,  2.726, 3.142, 0.30, 0.30),
    ("P03", -47.170, -1.707, 3.142, 0.30, 0.30),
    ("P04", -35.120, -0.857, 3.142, 0.30, 0.30),
    ("P05", -36.937,  3.976, 3.142, 0.30, 0.30),
]


def world_to_pixel(wx, wy, ox, oy, res, h_px):
    """World (x, y) → PGM pixel (col, row). PGM row 0 = top, world +y = north."""
    px = (wx - ox) / res
    py = h_px - 1 - (wy - oy) / res
    return px, py


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="pgm_in", required=True)
    ap.add_argument("--out", dest="pgm_out", required=True)
    ap.add_argument("--origin", nargs=2, type=float, required=True,
                    metavar=("OX", "OY"))
    ap.add_argument("--resolution", type=float, default=0.05)
    args = ap.parse_args()

    img = Image.open(args.pgm_in).convert("L")
    arr = np.array(img)
    h_px, w_px = arr.shape
    occ_before = int((arr < 50).sum())
    print(f"PGM {w_px}x{h_px}, occupied (before) = {occ_before} px")

    pil = Image.fromarray(arr)
    draw = ImageDraw.Draw(pil)

    for name, x, y, yaw, sx, sy in FURNITURE:
        hx, hy = sx / 2.0, sy / 2.0
        local = [(+hx, +hy), (-hx, +hy), (-hx, -hy), (+hx, -hy)]
        c, s = math.cos(yaw), math.sin(yaw)
        corners = []
        for lx, ly in local:
            wx = c * lx - s * ly + x
            wy = s * lx + c * ly + y
            px, py = world_to_pixel(wx, wy, args.origin[0], args.origin[1],
                                    args.resolution, h_px)
            corners.append((px, py))
        draw.polygon(corners, fill=0)
        print(f"  {name:14s}: world ({x:+7.3f}, {y:+7.3f}) yaw={yaw:+.3f} "
              f"size {sx}×{sy}")

    out_arr = np.array(pil)
    occ_after = int((out_arr < 50).sum())
    print(f"occupied (after)  = {occ_after} px (delta +{occ_after - occ_before})")
    Image.fromarray(out_arr).save(args.pgm_out)
    print(f"wrote: {args.pgm_out}")


if __name__ == "__main__":
    main()
