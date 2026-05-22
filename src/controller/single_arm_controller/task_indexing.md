# Task Indexing 작업 기록

serving_b1~b5 데이터셋의 task_index 라벨링 및 serving_b 병합까지의 전체 작업 기록.

---

## 1. Task 정의

모든 데이터셋 공통 (`meta/tasks.parquet`):

| task_index | instruction |
|---|---|
| 0 | pick up plate and place at target zone |
| 1 | pick up cup and place at target zone |
| 2 | return to home |

---

## 2. 라벨링 파이프라인

### 2.1 도구

| 스크립트 | 역할 |
|---|---|
| `scripts/gen_label_templates.py` | 에피소드 수와 frame_end에 맞는 label JSON 템플릿 생성. null은 수동 입력 필요 |
| `scripts/gripper_events.py` | action[5] (gripper) 신호를 분석해 start_close / fully_close / start_open 이벤트 검출 |
| `scripts/fill_boundaries.py` | gripper 이벤트 파일을 읽어 label JSON의 null 경계를 자동으로 채움 |
| `scripts/fill_b4_boundaries.py` | serving_b4 전용: ep0~9(2-boundary), ep10~19(3-boundary) 혼합 처리 |
| `scripts/apply_labels.py` | label JSON을 데이터셋 parquet에 실제 적용 (task_index 컬럼 덮어쓰기) |
| `scripts/apply_all_b_labels.sh` | serving_b1~b5에 일괄 적용 |
| `scripts/update_episode_tasks.py` | meta/episodes parquet의 tasks 컬럼을 실제 task 문자열로 갱신 |

### 2.2 gripper 이벤트 감지 원리

- `action[5]`가 gripper 위치값 (닫힘 ≈ 47, 열림 ≈ 55~65, 데이터셋마다 다름)
- 에피소드별 10th/90th percentile로 floor/ceiling 계산 → 고정 threshold 대신 자동 적응
- 상태머신: OPEN → TRANSIT_CLOSE → FULLY_CLOSE → CLOSED → TRANSIT_OPEN → OPEN
- TRANSIT_CLOSE 중 gripper가 다시 open_thresh 이상으로 올라가면 false close 판정 → 취소

| 이벤트 | 의미 |
|---|---|
| `start_close` | 그리퍼가 열린 상태에서 닫히기 시작 |
| `fully_close` | 그리퍼가 fully_close_thresh 이하로 처음 진입 (실제 grasp 시점) |
| `start_open` | 그리퍼가 닫힌 상태에서 열리기 시작 (place 시점) |

### 2.3 경계 결정 규칙

**경계 frame** = `fully_close` 이후 첫 번째 `start_open` 프레임

- 이 frame이 이전 task의 `end`, 다음 task의 `start = frame + 1`
- `fill_boundaries.py --from-last N`: 뒤에서 N번째 경계 사용 (기본값: 1 = 마지막)
- 경계가 N개 미만이면 자동으로 마지막 경계로 fallback

---

## 3. 데이터셋별 라벨링 내용

### serving_b1 — 접시 단독 (50 ep)

```
pattern : plate(0) → home(2)
경계    : 첫 번째 fully_close → start_open
도구    : fill_boundaries.py --events gripper_b1_1.txt --labels serving_b1.json
```

### serving_b2 — 컵 단독 (50 ep)

```
pattern : cup(1) → home(2)
경계    : 첫 번째 fully_close → start_open
도구    : fill_boundaries.py --events gripper_b2.txt --labels serving_b2.json
```

### serving_b3 — 연속 접시 2개 (20 ep)

```
pattern : plate(0) → plate(0) → home(2)
경계    : 1st fully_close→start_open, 2nd fully_close→start_open
도구    : fill_boundaries.py --skip 3  (ep3은 수동 라벨링)
비고    : plate1/plate2 모두 task_index=0이므로 data parquet에서는
          plate 구간이 하나로 보임. 시각 상태(접시 2개→1개)가 다름.
```

**ep3 (수동 라벨):**
```json
[
  {"start": 0,   "end": 410, "task_index": 0},
  {"start": 411, "end": 620, "task_index": 0},
  {"start": 621, "end": 711, "task_index": 2}
]
```

### serving_b4 — 연속 컵 2~3개 (20 ep)

```
ep 0~9  : cup(1) → cup(1) → home(2)        (2-boundary)
ep 10~19: cup(1) → cup(1) → cup(1) → home(2) (3-boundary)
도구    : fill_b4_boundaries.py (전용 스크립트)
```

### serving_b5 — 재시도 recovery (20 ep)

```
ep 0~9  : cup(1) → home(2)    (컵 재시도)
ep 10~19: plate(0) → home(2)  (접시 재시도)
경계    : 뒤에서 2번째 fully_close → start_open  (--from-last 2)
          경계가 1개뿐인 ep(1,2,6,7,14)는 마지막 경계로 fallback
비고    : 재시도 구간(grip 실패 반복)은 모두 같은 task_index로 유지.
          마지막 place 시점을 경계로 삼아 home과 분리.
```

---

## 4. 적용 순서

```bash
# 1. label JSON 템플릿 생성 (frame_end 자동 채움, 경계는 null)
uv run python scripts/gen_label_templates.py

# 2. gripper 이벤트 파일 생성
uv run python scripts/gripper_events.py --dataset datasets/serving_bX \
  --output datasets/labels/gripper_bX.txt

# 3. 경계 자동 채우기
uv run python scripts/fill_boundaries.py \
  --events datasets/labels/gripper_bX.txt \
  --labels datasets/labels/serving_bX.json

# 4. (b4 전용)
uv run python scripts/fill_b4_boundaries.py

# 5. label JSON → 데이터셋 일괄 적용
bash scripts/apply_all_b_labels.sh

# 6. meta/episodes tasks 컬럼 갱신
uv run python scripts/update_episode_tasks.py
```

**주의**: `apply_labels.py`의 백업 파일(`*.bak_*.parquet`)은 `datasets/{name}/backups/`에 저장됨.
`data/`나 `meta/` 내부에 백업이 남아 있으면 parquet glob에 잡혀 데이터가 2배로 읽힘.

---

## 5. serving_b 병합

### 소스 → 병합 에피소드 매핑

| 소스 | 원본 ep | 병합 후 ep | 에피소드 수 | 프레임 수 |
|---|---|---|---|---|
| serving_b1 | 0~49 | 0~49 | 50 | 17,277 |
| serving_b2 | 0~49 | 50~99 | 50 | 19,405 |
| serving_b3 | 0~19 | 100~119 | 20 | 12,927 |
| serving_b4 | 0~19 | 120~139 | 20 | 15,058 |
| serving_b5 | 0~19 | 140~159 | 20 | 10,422 |
| **합계** | | **0~159** | **160** | **75,089** |

### 병합 내용

- `data/` parquet: episode_index, index (global frame counter) 재번호 부여 후 concat
- `videos/`: ffmpeg concat demuxer로 mp4 파일 연결 (re-encoding 없음, av1 copy)
- `meta/episodes/`: episode_index, dataset_from/to_index, 비디오 timestamp offset 갱신
- `meta/tasks.parquet`: serving_b1 것 복사 (동일)
- `meta/info.json`: total_episodes=160, total_frames=75089, splits={'train':'0:160'}

```bash
uv run python scripts/merge_datasets.py \
  --sources datasets/serving_b1 datasets/serving_b2 datasets/serving_b3 \
            datasets/serving_b4 datasets/serving_b5 \
  --output  datasets/serving_b
```

---

## 6. HuggingFace 업로드

```bash
uv run python scripts/upload_dataset.py \
  --dataset datasets/serving_b \
  --repo-id jae0311/serving_b
```

업로드 결과: https://huggingface.co/datasets/jae0311/serving_b

- wrist 영상: 569 MB
- top 영상: 302 MB
- `backups/`, `labels/`, `*.bak_*` 제외하고 업로드

---

## 7. task_index 분포 (serving_b 최종)

| task_index | instruction | 프레임 수 |
|---|---|---|
| 0 | pick up plate | 24,981 |
| 1 | pick up cup | 29,929 |
| 2 | return to home | 20,179 |
| **합계** | | **75,089** |

---

## 8. 스크립트 전체 코드

### scripts/episode_info.py

```python
#!/usr/bin/env python3
"""
Print per-episode frame ranges and video seek positions for a dataset.

Usage:
  python scripts/episode_info.py --dataset datasets/serving_a2
  python scripts/episode_info.py --dataset datasets/serving_a2 --ep 3
  python scripts/episode_info.py --dataset datasets/serving_a2 --ep 3 --play
"""

import argparse
import glob
import json
import subprocess
import tempfile
from pathlib import Path

import pandas as pd


def load_df(dataset_dir: Path) -> pd.DataFrame:
    parquets = sorted(dataset_dir.glob("data/**/*.parquet"))
    return pd.concat([pd.read_parquet(p) for p in parquets], ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--ep", type=int, default=None)
    parser.add_argument("--cam", default="wrist")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    df = load_df(dataset_dir)
    summary = (
        df.groupby("episode_index")
        .agg(
            frame_start=("frame_index", "min"),
            frame_end=("frame_index", "max"),
            global_start=("index", "min"),
            global_end=("index", "max"),
        )
        .reset_index()
    )
    summary["seek_s"] = (summary["global_start"] / args.fps).round(2)
    summary["n_frames"] = summary["frame_end"] - summary["frame_start"] + 1

    vid_pattern = str(dataset_dir / "videos" / f"observation.images.{args.cam}" / "**" / "*.mp4")
    vid_files = sorted(glob.glob(vid_pattern, recursive=True))

    print(f"\nDataset : {dataset_dir.name}")
    print(f"Episodes: {len(summary)}")
    if vid_files:
        print(f"Video   : {vid_files[0]}")
    print()
    print(f"{'ep':>4}  {'seek(s)':>8}  {'frame_start':>11}  {'frame_end':>9}  {'n_frames':>8}")
    print("─" * 52)
    for _, row in summary.iterrows():
        ep = int(row["episode_index"])
        marker = " ◀" if args.ep is not None and ep == args.ep else ""
        print(f"{ep:>4}  {row['seek_s']:>8.2f}  {int(row['frame_start']):>11}  {int(row['frame_end']):>9}  {int(row['n_frames']):>8}{marker}")

    if args.ep is not None and vid_files:
        row = summary[summary["episode_index"] == args.ep]
        seek_s = float(row["seek_s"].iloc[0])
        end_s = (float(row["global_end"].iloc[0]) + 1) / args.fps
        frame_end = int(row["frame_end"].iloc[0])

        lua_script = f"""\
local seek_s = {seek_s:.3f}
local fps = {args.fps}
local frame_end = {frame_end}
mp.add_periodic_timer(1/30, function()
    local t = mp.get_property_number("time-pos")
    if t == nil then return end
    local ep_time = math.max(0, t - seek_s)
    local ep_frame = math.min(math.floor(ep_time * fps + 0.5), frame_end)
    mp.set_osd_ass(0, 0,
        "{{\\\\an7}}{{\\\\fs28}}frame: " .. ep_frame .. " / " .. frame_end
        .. "\\\\N" .. string.format("%.3fs", ep_time))
end)
"""
        cmd = ["mpv", f"--start={seek_s}", f"--end={end_s:.2f}",
               "--osd-level=0", f"--title=ep{args.ep} ({dataset_dir.name})", vid_files[0]]
        if args.play:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".lua", delete=False) as f:
                f.write(lua_script)
                lua_path = f.name
            try:
                subprocess.run(cmd + [f"--script={lua_path}"])
            finally:
                Path(lua_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
```

### scripts/dump_frame_ranges.py

```python
#!/usr/bin/env python3
"""
Print frame_start/frame_end for every episode in all datasets under datasets/.

Usage:
  python scripts/dump_frame_ranges.py
  python scripts/dump_frame_ranges.py --output frames.txt
  python scripts/dump_frame_ranges.py --datasets datasets/serving_a1 datasets/serving_a2
"""

import argparse
from pathlib import Path
import pandas as pd


def load_summary(dataset_dir: Path) -> pd.DataFrame:
    parquets = sorted(dataset_dir.glob("data/**/*.parquet"))
    if not parquets:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in parquets], ignore_index=True)
    summary = (
        df.groupby("episode_index")
        .agg(frame_start=("frame_index", "min"), frame_end=("frame_index", "max"))
        .reset_index()
    )
    summary["n_frames"] = summary["frame_end"] - summary["frame_start"] + 1
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", nargs="*")
    parser.add_argument("--output", default="frame_ranges.txt")
    args = parser.parse_args()

    dataset_dirs = [Path(d) for d in args.datasets] if args.datasets \
        else sorted(Path("datasets").glob("serving_*"))

    lines = []
    for dataset_dir in dataset_dirs:
        summary = load_summary(dataset_dir)
        if summary.empty:
            continue
        lines.append(f"{'=' * 52}")
        lines.append(f"{dataset_dir.name}  ({len(summary)} episodes)")
        lines.append(f"{'=' * 52}")
        lines.append(f"{'ep':>4}  {'frame_start':>11}  {'frame_end':>9}  {'n_frames':>8}")
        lines.append(f"{'─' * 40}")
        for _, row in summary.iterrows():
            lines.append(f"{int(row['episode_index']):>4}  {int(row['frame_start']):>11}  {int(row['frame_end']):>9}  {int(row['n_frames']):>8}")
        lines.append("")

    Path(args.output).write_text("\n".join(lines))
    print(f"Written to {args.output}  ({len(dataset_dirs)} datasets)")


if __name__ == "__main__":
    main()
```

### scripts/gen_label_templates.py

```python
#!/usr/bin/env python3
"""
Generate label JSON templates for all serving_* datasets.

- Fills in each episode's actual frame_end automatically.
- Leaves boundary frames as null — fill these in manually after watching videos.
- Output: datasets/labels/{dataset_name}.json

Usage:
  python scripts/gen_label_templates.py
  python scripts/gen_label_templates.py --datasets datasets/serving_b1 datasets/serving_b2
"""

import argparse
import json
from pathlib import Path
import pandas as pd

TASKS = [
    "pick up plate and place at target zone",
    "pick up cup and place at target zone",
    "return to home",
]

DATASET_PATTERNS = {
    "serving_a1": "cup_home",   "serving_a2": "plate_home",
    "serving_a3": "plate_home", "serving_a4": "cup_home",
    "serving_a5": "p_c_home",   "serving_a6": "p_c_home",
    "serving_a7": "home",
    "serving_b1": "plate_home", "serving_b2": "cup_home",
    "serving_b3": "pp_home",    "serving_b4": "cc_home",
    "serving_b5": "mixed_b5",
}


def make_segments(pattern: str, frame_end: int) -> list[dict]:
    def seg(start, end, ti):
        return {"start": start, "end": end, "task_index": ti}
    if pattern == "home":        return [seg(0, frame_end, 2)]
    if pattern == "plate_home":  return [seg(0, None, 0), seg(None, frame_end, 2)]
    if pattern == "cup_home":    return [seg(0, None, 1), seg(None, frame_end, 2)]
    if pattern == "p_c_home":    return [seg(0, None, 0), seg(None, None, 1), seg(None, frame_end, 2)]
    if pattern == "pp_home":     return [seg(0, None, 0), seg(None, None, 0), seg(None, frame_end, 2)]
    if pattern == "cc_home":     return [seg(0, None, 1), seg(None, None, 1), seg(None, frame_end, 2)]
    raise ValueError(f"Unknown pattern: {pattern}")


def gen_template(dataset_dir: Path, output_dir: Path):
    name = dataset_dir.name
    pattern = DATASET_PATTERNS.get(name)
    if not pattern:
        return
    parquets = sorted(dataset_dir.glob("data/**/*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parquets], ignore_index=True)
    frame_ends = df.groupby("episode_index")["frame_index"].max().to_dict()
    n_ep = len(frame_ends)
    episodes = {}
    for ep in range(n_ep):
        p = "cup_home" if (pattern == "mixed_b5" and ep < n_ep // 2) \
            else "plate_home" if pattern == "mixed_b5" else pattern
        episodes[str(ep)] = make_segments(p, int(frame_ends[ep]))
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{name}.json"
    with open(out, "w") as f:
        json.dump({"tasks": TASKS, "episodes": episodes}, f, indent=2, ensure_ascii=False)
    print(f"  {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", nargs="*")
    parser.add_argument("--output-dir", default="datasets/labels")
    args = parser.parse_args()
    dirs = [Path(d) for d in args.datasets] if args.datasets \
        else sorted(Path("datasets").glob("serving_*"))
    for d in dirs:
        gen_template(d, Path(args.output_dir))


if __name__ == "__main__":
    main()
```

### scripts/gripper_events.py

```python
#!/usr/bin/env python3
"""
Detect gripper open/close transition frames for every episode in a dataset.

Events:
  start_close : gripper begins closing  (pick moment)
  fully_close : gripper first crosses fully_close_thresh (actual grasp)
  start_open  : gripper begins opening  (place/release moment)

Thresholds adapt per-episode from actual signal range.

Usage:
  python scripts/gripper_events.py --dataset datasets/serving_b1
  python scripts/gripper_events.py --dataset datasets/serving_b1 --ep 0
  python scripts/gripper_events.py --dataset datasets/serving_b1 --output events.txt
"""

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

GRIPPER_IDX       = 5
SMOOTH_WINDOW     = 3
MIN_RANGE         = 2.0
OPEN_RATIO        = 0.80   # open_thresh  = floor + range * OPEN_RATIO
CLOSE_RATIO       = 0.10   # close_thresh = floor + range * CLOSE_RATIO
FULLY_CLOSE_RATIO = 0.15   # fully_close fires when value < floor + range * FULLY_CLOSE_RATIO
MOVE_RATIO        = 0.03   # move_thresh  = max(0.15, range * MOVE_RATIO)


def detect_events(gripper: np.ndarray) -> list[tuple[int, str]]:
    g = gripper.astype(float)
    if SMOOTH_WINDOW > 1:
        g = np.convolve(g, np.ones(SMOOTH_WINDOW) / SMOOTH_WINDOW, mode="same")

    floor, ceiling = np.percentile(g, 10), np.percentile(g, 90)
    rng = ceiling - floor
    if rng < MIN_RANGE:
        return []

    open_thresh        = floor + rng * OPEN_RATIO
    close_thresh       = floor + rng * CLOSE_RATIO
    fully_close_thresh = floor + rng * FULLY_CLOSE_RATIO
    move_thresh        = max(0.15, rng * MOVE_RATIO)
    diff = np.diff(g, prepend=g[0])

    state = "OPEN" if g[0] > open_thresh else "CLOSED" if g[0] < close_thresh else "UNKNOWN"
    events = []

    for i in range(len(g)):
        v, d = g[i], diff[i]
        if state == "OPEN":
            if d < -move_thresh:
                events.append((i, "start_close")); state = "TRANSIT_CLOSE"
        elif state == "CLOSED":
            if d > move_thresh:
                events.append((i, "start_open")); state = "TRANSIT_OPEN"
        elif state == "TRANSIT_CLOSE":
            if v < fully_close_thresh:
                events.append((i, "fully_close")); state = "TRANSIT_CLOSE_DONE"
            elif v > open_thresh:
                if events and events[-1][1] == "start_close": events.pop()
                state = "OPEN"
        elif state == "TRANSIT_CLOSE_DONE":
            if v < close_thresh:
                state = "CLOSED"
            elif v > open_thresh:
                if events and events[-1][1] == "fully_close": events.pop()
                if events and events[-1][1] == "start_close": events.pop()
                state = "OPEN"
        elif state == "TRANSIT_OPEN":
            if v > open_thresh: state = "OPEN"
        elif state == "UNKNOWN":
            if v > open_thresh: state = "OPEN"
            elif v < close_thresh: state = "CLOSED"
    return events


def process_dataset(dataset_dir: Path, ep_filter):
    parquets = sorted(dataset_dir.glob("data/**/*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parquets], ignore_index=True)
    results = []
    for ep, group in df.groupby("episode_index"):
        if ep_filter is not None and ep != ep_filter:
            continue
        gripper = np.array(group["action"].tolist())[:, GRIPPER_IDX]
        frame_end = int(group["frame_index"].max())
        for frame, etype in detect_events(gripper):
            results.append({"ep": int(ep), "frame": int(frame), "event": etype, "frame_end": frame_end})
    return results


def format_output(dataset_name, results):
    lines = [f"{'=' * 56}", dataset_name, f"{'=' * 56}",
             f"{'ep':>4}  {'frame':>6}  {'frame_end':>9}  {'pct':>6}  event", f"{'─' * 48}"]
    cur_ep = None
    for r in results:
        if r["ep"] != cur_ep:
            if cur_ep is not None: lines.append("")
            cur_ep = r["ep"]
        pct = r["frame"] / r["frame_end"] * 100 if r["frame_end"] > 0 else 0
        marker = {"start_close": "↓ start_close", "fully_close": "● fully_close",
                  "start_open": "↑ start_open "}.get(r["event"], r["event"])
        lines.append(f"{r['ep']:>4}  {r['frame']:>6}  {r['frame_end']:>9}  {pct:>5.1f}%  {marker}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--ep", type=int, default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    results = process_dataset(Path(args.dataset), args.ep)
    text = format_output(Path(args.dataset).name, results)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
        print(f"Written to {args.output}  ({len(results)} events)")
    else:
        print(text)


if __name__ == "__main__":
    main()
```

### scripts/fill_boundaries.py

```python
#!/usr/bin/env python3
"""
Fill null boundaries in label JSON using gripper event files.

Boundary rule: first 'start_open' after each 'fully_close' marks the end of
that task segment. Supports multiple boundaries per episode.

Usage:
  python scripts/fill_boundaries.py \
    --events datasets/labels/gripper_b1.txt \
    --labels datasets/labels/serving_b1.json

Options:
  --skip 3 7        : skip these episode numbers
  --from-last 2     : use 2nd-to-last boundary (fallback to last if unavailable)
"""

import argparse
import json
import re
from pathlib import Path


def parse_events(filepath):
    events = {}
    pattern = re.compile(r"^\s*(\d+)\s+(\d+)\s+\d+\s+(?:[\d.]+%\s+)?[↑↓●]\s+(\S+)")
    for line in open(filepath, encoding="utf-8"):
        m = pattern.match(line)
        if m:
            ep, frame, event = int(m.group(1)), int(m.group(2)), m.group(3)
            events.setdefault(ep, []).append((frame, event))
    return events


def find_boundaries(ep_events):
    boundaries, saw_close = [], False
    for frame, event in ep_events:
        if event in ("close", "start_close", "fully_close"):
            saw_close = True
        elif event in ("open", "start_open") and saw_close:
            boundaries.append(frame)
            saw_close = False
    return boundaries


def fill_labels(labels_path, boundaries_map):
    with open(labels_path, encoding="utf-8") as f:
        labels = json.load(f)
    filled, missing = 0, []
    for ep_str, segments in labels["episodes"].items():
        ep = int(ep_str)
        boundaries = boundaries_map.get(ep)
        if not boundaries:
            missing.append(ep); continue
        for i, boundary in enumerate(boundaries[:len(segments) - 1]):
            segments[i]["end"]       = boundary
            segments[i + 1]["start"] = boundary + 1
        filled += 1
    with open(labels_path, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)
    return filled, missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--skip", type=int, nargs="*", default=[])
    parser.add_argument("--from-last", type=int, default=1)
    args = parser.parse_args()

    ep_events  = parse_events(Path(args.events))
    boundaries = {ep: find_boundaries(evs) for ep, evs in ep_events.items()}
    skip = set(args.skip)
    if skip:
        boundaries = {ep: b for ep, b in boundaries.items() if ep not in skip}

    n = args.from_last
    selected, fallback_eps = {}, []
    for ep, bs in boundaries.items():
        if not bs:                selected[ep] = []
        elif len(bs) >= n:        selected[ep] = [bs[-n]]
        else:                     selected[ep] = [bs[-1]]; fallback_eps.append(ep)

    if fallback_eps:
        print(f"[fallback to last boundary] episodes: {sorted(fallback_eps)}")

    filled, missing = fill_labels(Path(args.labels), selected)
    print(f"Updated {Path(args.labels).name}: {filled} episodes filled"
          + (f", {len(missing)} skipped: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
```

### scripts/fill_b4_boundaries.py

```python
#!/usr/bin/env python3
"""
Fill serving_b4.json boundaries from gripper_b4.txt.

  ep  0~ 9 : 3 segments (1 → 1 → 2),       2 boundaries
  ep 10~19 : 4 segments (1 → 1 → 1 → 2),   3 boundaries

Run from project root: uv run python scripts/fill_b4_boundaries.py
"""

import json, re
from pathlib import Path

EVENTS_FILE = Path("datasets/labels/gripper_b4.txt")
LABELS_FILE = Path("datasets/labels/serving_b4.json")


def parse_events(filepath):
    events = {}
    pat = re.compile(r"^\s*(\d+)\s+(\d+)\s+\d+\s+(?:[\d.]+%\s+)?[↑↓●]\s+(\S+)")
    for line in filepath.read_text(encoding="utf-8").splitlines():
        m = pat.match(line)
        if m:
            ep, frame, event = int(m.group(1)), int(m.group(2)), m.group(3)
            events.setdefault(ep, []).append((frame, event))
    return events


def find_boundaries(ep_events):
    boundaries, saw_close = [], False
    for frame, event in ep_events:
        if event in ("close", "start_close", "fully_close"):
            saw_close = True
        elif event in ("open", "start_open") and saw_close:
            boundaries.append(frame); saw_close = False
    return boundaries


def main():
    ep_events = parse_events(EVENTS_FILE)
    bmap = {ep: find_boundaries(evs) for ep, evs in ep_events.items()}
    labels = json.load(open(LABELS_FILE, encoding="utf-8"))

    for ep_str, segments in labels["episodes"].items():
        ep = int(ep_str)
        bs = bmap.get(ep, [])
        frame_end = segments[-1]["end"]
        if ep <= 9 and len(bs) >= 2:
            labels["episodes"][ep_str] = [
                {"start": 0,         "end": bs[0],     "task_index": 1},
                {"start": bs[0] + 1, "end": bs[1],     "task_index": 1},
                {"start": bs[1] + 1, "end": frame_end, "task_index": 2},
            ]
        elif ep >= 10 and len(bs) >= 3:
            labels["episodes"][ep_str] = [
                {"start": 0,         "end": bs[0],     "task_index": 1},
                {"start": bs[0] + 1, "end": bs[1],     "task_index": 1},
                {"start": bs[1] + 1, "end": bs[2],     "task_index": 1},
                {"start": bs[2] + 1, "end": frame_end, "task_index": 2},
            ]

    with open(LABELS_FILE, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)
    print(f"Done. {LABELS_FILE}")


if __name__ == "__main__":
    main()
```

### scripts/apply_labels.py

```python
#!/usr/bin/env python3
"""
Apply label JSON to a LeRobot dataset's parquet files and metadata.

Updates:
  data/**/*.parquet     → task_index column per frame
  meta/tasks.parquet    → task string definitions
  meta/info.json        → total_tasks count

Backups are saved to datasets/{name}/backups/.

Usage:
  python scripts/apply_labels.py --dataset datasets/serving_b1 --labels datasets/labels/serving_b1.json
  python scripts/apply_labels.py ... --dry-run
"""

import argparse, json, shutil
from datetime import datetime
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def backup(path: Path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_dir = path.parents[2] / "backups"
    bak_dir.mkdir(exist_ok=True)
    bak = bak_dir / f"{path.stem}.bak_{ts}{path.suffix}"
    shutil.copy2(path, bak)
    print(f"  backed up → backups/{bak.name}")


def apply(dataset_dir, labels, dry_run=False):
    dataset_path = Path(dataset_dir)
    tasks, episodes = labels["tasks"], labels["episodes"]

    frame_map = {}
    for ep_str, segments in episodes.items():
        ep_idx = int(ep_str)
        for seg in segments:
            for f in range(seg["start"], seg["end"] + 1):
                frame_map[(ep_idx, f)] = seg["task_index"]

    for pq_path in sorted(dataset_path.glob("data/**/*.parquet")):
        df = pd.read_parquet(pq_path)
        new_task = df.apply(
            lambda row: frame_map.get((int(row["episode_index"]), int(row["frame_index"])),
                                      int(row["task_index"])), axis=1).astype("int64")
        changed = (new_task != df["task_index"]).sum()
        if not dry_run and changed > 0:
            backup(pq_path)
            df["task_index"] = new_task
            pq.write_table(pa.Table.from_pandas(df, preserve_index=False), pq_path)
        print(f"  {pq_path.relative_to(dataset_path)}: {changed} frames updated")

    tasks_path = dataset_path / "meta" / "tasks.parquet"
    tasks_df = pd.DataFrame({"task_index": list(range(len(tasks))), "task": tasks}).set_index("task")
    if not dry_run:
        if tasks_path.exists(): backup(tasks_path)
        pq.write_table(pa.Table.from_pandas(tasks_df), tasks_path)

    info_path = dataset_path / "meta" / "info.json"
    info = json.load(open(info_path))
    info["total_tasks"] = len(tasks)
    if not dry_run:
        backup(info_path)
        json.dump(info, open(info_path, "w"), indent=4)

    if dry_run:
        print("\n[dry-run] No files were modified.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    labels = json.load(open(args.labels))
    apply(args.dataset, labels, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

### scripts/apply_all_b_labels.sh

```bash
#!/usr/bin/env bash
# Apply label JSONs from datasets/labels/ to each serving_b* dataset.
# Run from project root: bash scripts/apply_all_b_labels.sh
# Add --dry-run to preview without modifying files.

set -e
DRYRUN=${1:-}

for ds in serving_b1 serving_b2 serving_b3 serving_b4 serving_b5; do
    echo "========================================"
    echo "  ${ds}"
    echo "========================================"
    uv run python scripts/apply_labels.py \
        --dataset "datasets/${ds}" \
        --labels  "datasets/labels/${ds}.json" \
        $DRYRUN
    echo ""
done

echo "All done."
```

### scripts/update_episode_tasks.py

```python
#!/usr/bin/env python3
"""
Update meta/episodes tasks column to reflect actual task strings used per episode.

Usage:
  python scripts/update_episode_tasks.py --dataset datasets/serving_b1
  python scripts/update_episode_tasks.py   # all serving_b* datasets
"""

import argparse, shutil
from datetime import datetime
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def update_dataset(dataset_dir: Path):
    tasks_df = pd.read_parquet(dataset_dir / "meta" / "tasks.parquet")
    task_map = {int(v): k for k, v in tasks_df["task_index"].items()}

    parquets = [p for p in sorted(dataset_dir.glob("data/**/*.parquet")) if ".bak_" not in p.name]
    df = pd.concat([pd.read_parquet(p) for p in parquets], ignore_index=True)

    ep_tasks = (
        df.groupby("episode_index")["task_index"]
        .apply(lambda s: sorted({task_map[int(i)] for i in s.unique()}))
        .to_dict()
    )

    for ep_path in sorted(dataset_dir.glob("meta/episodes/**/*.parquet")):
        if ".bak_" in ep_path.name:
            continue
        ep_df = pd.read_parquet(ep_path)
        ep_df["tasks"] = ep_df["episode_index"].map(
            lambda ep: ep_tasks.get(int(ep), ep_df.loc[ep_df["episode_index"] == ep, "tasks"].iloc[0])
        )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(ep_path, ep_path.with_suffix(f".bak_{ts}.parquet"))
        pq.write_table(pa.Table.from_pandas(ep_df, preserve_index=False), ep_path)

    print(f"  {dataset_dir.name}: updated")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=None)
    args = parser.parse_args()
    dirs = [Path(args.dataset)] if args.dataset else sorted(Path("datasets").glob("serving_b*"))
    for d in dirs:
        update_dataset(d)


if __name__ == "__main__":
    main()
```

### scripts/merge_datasets.py

```python
#!/usr/bin/env python3
"""
Merge multiple LeRobot datasets into one.

Merges:
  - data parquets (re-numbered episode_index, index)
  - videos (ffmpeg concat, no re-encoding)
  - meta/episodes (re-numbered indices and video timestamps)
  - meta/tasks.parquet (copied from first source)
  - meta/info.json (updated totals)

Usage:
  python scripts/merge_datasets.py \
    --sources datasets/serving_b1 datasets/serving_b2 ... \
    --output  datasets/serving_b
"""

import argparse, json, shutil, subprocess, tempfile
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def _real_parquets(glob_result):
    return [p for p in glob_result if ".bak_" not in p.name]


def load_data(d):
    return pd.concat([pd.read_parquet(p) for p in _real_parquets(sorted(d.glob("data/**/*.parquet")))],
                     ignore_index=True)


def load_episodes(d):
    return pd.concat([pd.read_parquet(p) for p in _real_parquets(sorted(d.glob("meta/episodes/**/*.parquet")))],
                     ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", required=True)
    parser.add_argument("--output",  required=True)
    args = parser.parse_args()

    src_dirs = [Path(s) for s in args.sources]
    out_dir  = Path(args.output)
    cams = [p.name for p in (src_dirs[0] / "videos").iterdir() if p.is_dir()]
    fps  = json.load(open(src_dirs[0] / "meta" / "info.json"))["fps"]

    src_meta, ep_offset, frame_offset = [], 0, 0
    vid_offset = {cam: 0.0 for cam in cams}
    for d in src_dirs:
        data_df, ep_df = load_data(d), load_episodes(d)
        m = {"dir": d, "data_df": data_df, "ep_df": ep_df,
             "n_ep": ep_df["episode_index"].nunique(), "n_frames": len(data_df),
             "ep_offset": ep_offset, "frame_offset": frame_offset,
             "vid_offset": dict(vid_offset)}
        src_meta.append(m)
        ep_offset    += m["n_ep"]
        frame_offset += m["n_frames"]
        for cam in cams:
            vid_offset[cam] += m["ep_df"][f"videos/{cam}/to_timestamp"].iloc[-1]

    # Merge data
    merged_df = pd.concat([
        m["data_df"].assign(episode_index=m["data_df"]["episode_index"] + m["ep_offset"],
                            index=m["data_df"]["index"] + m["frame_offset"])
        for m in src_meta], ignore_index=True)
    out_data = out_dir / "data" / "chunk-000"
    out_data.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(merged_df, preserve_index=False), out_data / "file-000.parquet")

    # Concat videos
    for cam in cams:
        out_vid = out_dir / "videos" / cam / "chunk-000"
        out_vid.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for m in src_meta:
                f.write(f"file '{(m[\"dir\"] / \"videos\" / cam / \"chunk-000\" / \"file-000.mp4\").resolve()}'\n")
            list_path = f.name
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", list_path, "-c", "copy", str(out_vid / "file-000.mp4")],
                       check=True, capture_output=True)
        Path(list_path).unlink()

    # Merge episodes
    ep_parts = []
    for m in src_meta:
        ep = m["ep_df"].copy()
        ep["episode_index"] += m["ep_offset"]
        ep["dataset_from_index"] += m["frame_offset"]
        ep["dataset_to_index"]   += m["frame_offset"]
        ep["data/chunk_index"] = ep["data/file_index"] = 0
        for cam in cams:
            off = m["vid_offset"][cam]
            ep[f"videos/{cam}/from_timestamp"] += off
            ep[f"videos/{cam}/to_timestamp"]   += off
            ep[f"videos/{cam}/chunk_index"] = ep[f"videos/{cam}/file_index"] = 0
        for stat in ["min","max","mean","q01","q10","q50","q90","q99"]:
            for col, add in [(f"stats/episode_index/{stat}", m["ep_offset"]),
                             (f"stats/index/{stat}",         m["frame_offset"])]:
                if col in ep.columns:
                    ep[col] = ep[col].apply(lambda v, a=add: [x+a for x in v] if isinstance(v,list) else v+a)
        ep_parts.append(ep)

    merged_ep = pd.concat(ep_parts, ignore_index=True)
    merged_ep["meta/episodes/chunk_index"] = merged_ep["meta/episodes/file_index"] = 0
    out_ep = out_dir / "meta" / "episodes" / "chunk-000"
    out_ep.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(merged_ep, preserve_index=False), out_ep / "file-000.parquet")

    # tasks + info
    out_meta = out_dir / "meta"
    out_meta.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_dirs[0] / "meta" / "tasks.parquet", out_meta / "tasks.parquet")
    info = json.load(open(src_dirs[0] / "meta" / "info.json"))
    info.update({"total_episodes": ep_offset, "total_frames": frame_offset,
                 "splits": {"train": f"0:{ep_offset}"}})
    json.dump(info, open(out_meta / "info.json", "w"), indent=4)
    print(f"Done. episodes={ep_offset}, frames={frame_offset}")


if __name__ == "__main__":
    main()
```

### scripts/upload_dataset.py

```python
#!/usr/bin/env python3
"""
Upload a LeRobot dataset directory to HuggingFace Hub.

Usage:
  python scripts/upload_dataset.py \
    --dataset datasets/serving_b \
    --repo-id jae0311/serving_b
  python scripts/upload_dataset.py ... --private
"""

import argparse
from pathlib import Path
from huggingface_hub import HfApi, create_repo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset",  required=True)
    parser.add_argument("--repo-id",  required=True)
    parser.add_argument("--private",  action="store_true")
    args = parser.parse_args()

    api = HfApi()
    create_repo(args.repo_id, repo_type="dataset", exist_ok=True, private=args.private)
    print(f"Repo: https://huggingface.co/datasets/{args.repo_id}")

    api.upload_folder(
        folder_path=str(Path(args.dataset)),
        repo_id=args.repo_id,
        repo_type="dataset",
        ignore_patterns=["backups/*", "labels/*", "*.bak_*"],
    )
    print(f"Done.\nhttps://huggingface.co/datasets/{args.repo_id}")


if __name__ == "__main__":
    main()
```
