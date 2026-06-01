#!/usr/bin/env python3
"""
데이터셋 top 비디오의 형광등 banding 제거 스크립트.

고정 overlay 방식이 아닌 프레임별 FFT 분석으로 120px 주기의 banding 성분을
추정하고 제거한다. 위상과 진폭이 프레임마다 변하므로 per-frame 접근이 필요.

각 프레임 처리:
  1. 행(row) 방향 평균으로 1D 신호 추출
  2. 120px 주기의 cos/sin 성분 투영 (FFT 대신 직접 내적)
  3. 추정된 banding 성분을 프레임에서 빼기

Usage:
    python3 destripe_dataset_top.py [--dataset-dir PATH] [--dry-run] [--backup]
                                    [--single FILENAME] [--period PX]
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


PERIOD_PX   = 120.0   # 분석으로 확인된 banding 주기 (픽셀)
HEIGHT      = 480
WIDTH       = 640

DATASET_DEFAULT = Path.home() / '.cache/huggingface/lerobot/jae0311/pickup_20260526_121722'
TOP_VIDEO_GLOB  = 'videos/observation.images.top/**/*.mp4'


def destripe_frame(frame: np.ndarray, period_px: float) -> np.ndarray:
    """전체 행 정규화(full row normalization)로 banding 제거.

    각 행의 평균 밝기를 전역 평균으로 평탄화한다.
    주기에 무관하게 모든 수평 banding을 제거한다.
    """
    f32 = frame.astype(np.float32)
    row_means = f32.mean(axis=(1, 2))          # (H,) 각 행의 평균 밝기
    global_mean = row_means.mean()             # 전체 평균
    correction = (row_means - global_mean)[:, np.newaxis, np.newaxis]
    return np.clip(f32 - correction, 0, 255).astype(np.uint8)


def _probe_video(src: Path) -> tuple[int, int, float]:
    """ffprobe로 (width, height, fps) 반환."""
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(src)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(result.stdout)['streams']
    v = next(s for s in streams if s['codec_type'] == 'video')
    num, den = map(int, v['r_frame_rate'].split('/'))
    return int(v['width']), int(v['height']), num / den


def destripe_video(src: Path, dst: Path, period_px: float) -> int:
    """ffmpeg 파이프로 AV1 디코딩 → per-frame banding 제거 → AV1 재인코딩."""
    width, height, fps = _probe_video(src)
    frame_bytes = width * height * 3

    decode_cmd = [
        'ffmpeg', '-hwaccel', 'cuda', '-c:v', 'av1_cuvid',
        '-i', str(src),
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1',
    ]
    encode_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', str(fps),
        '-i', 'pipe:0',
        '-c:v', 'av1_nvenc', '-cq', '35', '-preset', 'p4',
        '-pix_fmt', 'yuv420p', '-an',
        str(dst),
    ]

    dec = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    enc = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    frame_count = 0
    try:
        while True:
            raw = dec.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy()
            cleaned = destripe_frame(frame, period_px)
            enc.stdin.write(cleaned.tobytes())
            frame_count += 1
    finally:
        dec.stdout.close()
        dec.wait()
        enc.stdin.close()
        enc.wait()

    if enc.returncode != 0:
        raise RuntimeError(f'ffmpeg encode failed (rc={enc.returncode}) for {src}')

    return frame_count


def main():
    parser = argparse.ArgumentParser(
        description='Remove per-frame fluorescent banding from LeRobot top videos'
    )
    parser.add_argument('--dataset-dir', type=Path, default=DATASET_DEFAULT)
    parser.add_argument('--dry-run', action='store_true',
                        help='목록만 출력하고 실제로 변경하지 않음')
    parser.add_argument('--backup', action='store_true',
                        help='원본 파일을 .mp4.orig 로 백업 (이미 존재하면 스킵)')
    parser.add_argument('--single', metavar='FILENAME',
                        help='지정 파일 하나만 처리 (예: file-000.mp4). 테스트용.')
    parser.add_argument('--period', type=float, default=PERIOD_PX,
                        help=f'banding 주기(px) (기본: {PERIOD_PX})')
    args = parser.parse_args()

    dataset_dir: Path = args.dataset_dir
    if not dataset_dir.exists():
        print(f'[ERROR] Dataset directory not found: {dataset_dir}', file=sys.stderr)
        sys.exit(1)

    all_videos = sorted(dataset_dir.glob(TOP_VIDEO_GLOB))
    if not all_videos:
        print(f'[ERROR] No top videos found.', file=sys.stderr)
        sys.exit(1)

    if args.single:
        videos = [v for v in all_videos if v.name == args.single]
        if not videos:
            print(f'[ERROR] "{args.single}" not found in dataset.', file=sys.stderr)
            sys.exit(1)
    else:
        videos = all_videos

    print(f'Per-frame banding removal  period={args.period}px')
    print(f'Processing {len(videos)} / {len(all_videos)} video(s).\n')

    for video_path in videos:
        rel = video_path.relative_to(dataset_dir)
        orig_path = video_path.with_suffix('.mp4.orig')
        source_path = orig_path if orig_path.exists() else video_path

        print(f'  {rel}  [src: {"*.orig" if source_path == orig_path else "mp4"}]',
              end='', flush=True)

        if args.dry_run:
            print('  [dry-run]')
            continue

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            n = destripe_video(source_path, tmp_path, args.period)
            print(f'  {n} frames', end='')

            if args.backup and not orig_path.exists():
                shutil.copy2(video_path, orig_path)
                print(f' -> backup: {orig_path.name}', end='')

            shutil.move(str(tmp_path), str(video_path))
            print('  [done]')
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            print(f'  [FAILED: {e}]')
            sys.exit(1)

    print('\nAll done.')


if __name__ == '__main__':
    main()
