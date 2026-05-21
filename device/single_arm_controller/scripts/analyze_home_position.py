#!/usr/bin/env python3
"""
관절값 로그 파일을 읽어 홈 포지션 범위를 분석하고 serving.py에 쓸 수 있는 형태로 출력.

Usage:
    python analyze_home_position.py                      # 기본 경로 /tmp/joint_log.npy
    python analyze_home_position.py --log /tmp/joint_log.npy
    python analyze_home_position.py --log /tmp/joint_log.npy --output home_range.json
"""

import argparse
import json
from pathlib import Path

import numpy as np

MOTOR_NAMES = [
    'shoulder_pan',   # 0
    'shoulder_lift',  # 1
    'elbow_flex',     # 2
    'wrist_flex',     # 3
    'wrist_roll',     # 4
    'gripper',        # 5
]

# serving.py에서 현재 사용 중인 홈 포지션 범위 (비교용)
CURRENT_HOME_RANGE = {
    1: (-67.0, -50.0),
    2: ( 50.0,  56.0),
    4: (-10.0,   8.0),
}


def load_log(path: str) -> np.ndarray:
    """npy 파일 로드. shape: (N, 7) = [timestamp, j0, j1, j2, j3, j4, j5]"""
    data = np.load(path)
    print(f"Loaded {len(data)} frames from {path}")
    print(f"Duration: {data[-1, 0]:.1f}s\n")
    return data


def find_clusters(data: np.ndarray, margin_s: float = 5.0):
    """
    시계열에서 처음 margin_s초와 마지막 margin_s초를 홈 포지션 후보로 추출.
    실제 작업 구간은 중간 부분.
    """
    t = data[:, 0]
    total = t[-1]

    start_mask = t <= margin_s
    end_mask   = t >= (total - margin_s)
    mid_mask   = ~start_mask & ~end_mask

    start_frames = data[start_mask, 1:]
    end_frames   = data[end_mask,   1:]
    mid_frames   = data[mid_mask,   1:]
    home_frames  = np.concatenate([start_frames, end_frames], axis=0)

    return home_frames, mid_frames, start_frames, end_frames


def compute_range(frames: np.ndarray, sigma: float = 2.0, extra_margin: float = 0.0):
    """mean ± (sigma*std + extra_margin) 범위 계산."""
    means = frames.mean(axis=0)
    stds  = frames.std(axis=0)
    lo    = means - sigma * stds - extra_margin
    hi    = means + sigma * stds + extra_margin
    return means, stds, lo, hi


def print_analysis(home_frames, mid_frames, lo, hi, means, stds):
    print(f"{'Motor':<16} {'home_mean':>10} {'home_std':>9} "
          f"{'mid_mean':>9} {'diff':>7} {'proposed_lo':>11} {'proposed_hi':>11} {'separable':>10}")
    print('-' * 95)

    for i, name in enumerate(MOTOR_NAMES):
        home_mean = home_frames[:, i].mean()
        home_std  = home_frames[:, i].std()
        mid_mean  = mid_frames[:, i].mean() if len(mid_frames) > 0 else float('nan')
        diff      = abs(home_mean - mid_mean)
        sep       = 'YES' if diff > 3 * home_std else ('maybe' if diff > home_std else 'NO')

        current = CURRENT_HOME_RANGE.get(i)
        flag = ''
        if current:
            in_range = current[0] <= home_mean <= current[1]
            flag = '✓' if in_range else ' ← OUT OF CURRENT RANGE'

        print(f"{name:<16} {home_mean:>10.2f} {home_std:>9.2f} "
              f"{mid_mean:>9.2f} {diff:>7.2f} "
              f"{lo[i]:>11.2f} {hi[i]:>11.2f} {sep:>10}  {flag}")


def build_home_range(lo: np.ndarray, hi: np.ndarray, mid_frames: np.ndarray,
                     home_frames: np.ndarray) -> dict:
    """
    mid-task와 잘 구분되는 관절만 선택해 홈 포지션 범위 딕셔너리 생성.
    separability = |home_mean - mid_mean| / home_std
    """
    selected = {}
    for i in range(len(MOTOR_NAMES)):
        home_mean = home_frames[:, i].mean()
        home_std  = home_frames[:, i].std()
        mid_mean  = mid_frames[:, i].mean() if len(mid_frames) > 0 else home_mean
        sep_score = abs(home_mean - mid_mean) / (home_std + 1e-6)

        if sep_score > 3.0:
            selected[i] = (round(float(lo[i]), 2), round(float(hi[i]), 2))

    return selected


def save_output(home_range: dict, path: str):
    out = {
        'home_range': {str(k): list(v) for k, v in home_range.items()},
        'motor_names': {str(i): name for i, name in enumerate(MOTOR_NAMES)},
        'note': (
            'Keys are joint indices. '
            'Copy _HOME_RANGE in serving.py with these values.'
        ),
    }
    with open(path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log',    default='/tmp/joint_log.npy',
                        help='Path to joint_log.npy (default: /tmp/joint_log.npy)')
    parser.add_argument('--margin', type=float, default=5.0,
                        help='Seconds at start/end considered home position (default: 5)')
    parser.add_argument('--sigma',        type=float, default=4.0,
                        help='Range = mean ± sigma*std (default: 4.0)')
    parser.add_argument('--extra-margin', type=float, default=5.0,
                        help='Fixed extra margin added on both sides (default: 5.0)')
    parser.add_argument('--output', default=None,
                        help='Save result JSON to this path')
    args = parser.parse_args()

    data = load_log(args.log)
    home_frames, mid_frames, start_f, end_f = find_clusters(data, margin_s=args.margin)

    means, stds, lo, hi = compute_range(home_frames, sigma=args.sigma,
                                        extra_margin=args.extra_margin)

    print(f"=== 홈 포지션 분석 (처음/마지막 {args.margin}s, "
          f"sigma={args.sigma}, extra_margin=±{args.extra_margin}) ===\n")
    print(f"홈 프레임: {len(home_frames)}  (시작 {len(start_f)} + 끝 {len(end_f)})")
    print(f"작업 프레임: {len(mid_frames)}\n")

    print_analysis(home_frames, mid_frames, lo, hi, means, stds)

    home_range = build_home_range(lo, hi, mid_frames, home_frames)

    print(f"\n=== serving.py에 사용할 _HOME_RANGE (자동 선택) ===\n")
    print("_HOME_RANGE = {")
    for idx, (l, h) in home_range.items():
        print(f"    {idx}: ({l}, {h}),   # {MOTOR_NAMES[idx]}")
    print("}")

    print(f"\n=== 현재 serving.py의 _HOME_RANGE 비교 ===")
    for idx, (cur_lo, cur_hi) in CURRENT_HOME_RANGE.items():
        new_range = home_range.get(idx)
        if new_range:
            lo_diff = abs(cur_lo - new_range[0])
            hi_diff = abs(cur_hi - new_range[1])
            print(f"  {MOTOR_NAMES[idx]}: "
                  f"현재 [{cur_lo}, {cur_hi}] → 제안 [{new_range[0]}, {new_range[1]}]  "
                  f"(lo diff={lo_diff:.1f}, hi diff={hi_diff:.1f})")
        else:
            print(f"  {MOTOR_NAMES[idx]}: 현재 범위 [{cur_lo}, {cur_hi}] → 새 분석에서 제외됨")

    if args.output:
        save_output(home_range, args.output)
    else:
        tmp_out = '/tmp/home_range.json'
        save_output(home_range, tmp_out)
        print(f"(--output 미지정, 기본 저장: {tmp_out})")


if __name__ == '__main__':
    main()
