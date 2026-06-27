#!/usr/bin/env python3
"""Numerically test case/bread contact friction using the exported SDF collisions."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
GZ = shutil.which("gz") or "/opt/ros/jazzy/bin/gz"
MODEL_ROOT = REPO_ROOT / "src/controller/ddooby_controller/assets/manufacturing_world/models"

WORLD_TEMPLATE = """<?xml version=\"1.0\"?>
<sdf version=\"1.9\">
  <world name=\"default\">
    <gravity>{gx} {gy} -9.81</gravity>
    <physics name=\"case_bread_contact_physics\" default=\"true\" type=\"ignored\">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>1000</real_time_update_rate>
      <max_contacts>80</max_contacts>
      <dart>
        <collision_detector>ode</collision_detector>
        <solver>
          <solver_type>dantzig</solver_type>
        </solver>
      </dart>
    </physics>
    <plugin filename=\"gz-sim-physics-system\" name=\"gz::sim::systems::Physics\"/>
    <plugin filename=\"gz-sim-user-commands-system\" name=\"gz::sim::systems::UserCommands\"/>
    <plugin filename=\"gz-sim-scene-broadcaster-system\" name=\"gz::sim::systems::SceneBroadcaster\"/>

{case_model}

{bread_model}
  </world>
</sdf>
"""


def model_block(name: str) -> str:
    text = (MODEL_ROOT / name / "model.sdf").read_text(encoding="utf-8")
    match = re.search(r"<model\b.*?</model>", text, flags=re.S)
    if not match:
        raise RuntimeError(f"Could not extract model from {name}")
    block = match.group(0)
    # Headless physics test: visual meshes are irrelevant and can introduce resource noise.
    block = re.sub(r"\n\s*<visual\b.*?</visual>", "", block, flags=re.S)
    return block


def set_model_name(block: str, old: str, new: str) -> str:
    block = re.sub(rf'<model name="{re.escape(old)}">', f'<model name="{new}">', block, count=1)
    block = block.replace(f'<link name="{old}_link">', f'<link name="{new}_link">')
    return block


def set_static_and_pose(block: str, static: bool, pose: str) -> str:
    block = re.sub(r"<static>.*?</static>", f"<static>{str(static).lower()}</static>", block, count=1)
    block = re.sub(r"(<static>.*?</static>)", rf"\1\n    <pose>{pose}</pose>", block, count=1)
    return block


def set_mu(block: str, mu: float) -> str:
    block = re.sub(r"<mu>[-+0-9.eE]+</mu>", f"<mu>{mu}</mu>", block)
    block = re.sub(r"<mu2>[-+0-9.eE]+</mu2>", f"<mu2>{mu}</mu2>", block)
    return block


def make_world(path: Path, mu: float, gx: float, gy: float, case_pitch_deg: float, bread_x: float, bread_y: float) -> None:
    case = model_block("case")
    bread = model_block("bread1")
    case = set_model_name(case, "case", "case_probe")
    bread = set_model_name(bread, "bread1", "bread_probe")
    case = set_mu(case, mu)
    bread = set_mu(bread, mu)

    case_pitch = case_pitch_deg * 3.141592653589793 / 180.0
    # case bottom top is roughly local z=-0.01244. bread bottom lower is roughly local z=-0.01540.
    # bread model z = case_z -0.01244 +0.01540 + small clearance.
    case_z = 0.050
    bread_z = case_z + 0.0032
    case = set_static_and_pose(case, True, f"0 0 {case_z:.6f} 0 {case_pitch:.9f} 0")
    bread = set_static_and_pose(bread, False, f"{bread_x:.6f} {bread_y:.6f} {bread_z:.6f} 0 0 0")
    path.write_text(WORLD_TEMPLATE.format(gx=gx, gy=gy, case_model=case, bread_model=bread), encoding="utf-8")


def extract_pose(text: str, model_name: str) -> tuple[float, float, float] | None:
    pattern = rf'name:\s*"{re.escape(model_name)}"(?P<body>.*?)(?=\nname:\s*"|$)'
    for match in re.finditer(pattern, text, flags=re.S):
        pose_match = re.search(r"position\s*\{(?P<pos>.*?)\}", match.group("body"), flags=re.S)
        if not pose_match:
            continue
        pos = pose_match.group("pos")
        values = []
        for axis in ("x", "y", "z"):
            axis_match = re.search(rf"\b{axis}:\s*([-+0-9.eE]+)", pos)
            if not axis_match:
                return None
            values.append(float(axis_match.group(1)))
        return tuple(values)  # type: ignore[return-value]
    return None


def sample_pose(model_name: str, timeout_sec: float = 2.0) -> tuple[float, float, float] | None:
    cmd = [GZ, "topic", "-e", "-t", "/world/default/pose/info", "-n", "1"]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout_sec)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return extract_pose(out, model_name)


def terminate(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=3.0)


def run_once(mu: float, gx: float, gy: float, duration_sec: float, case_pitch_deg: float, bread_x: float, bread_y: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ddooby_case_bread_") as tmp:
        world = Path(tmp) / f"case_bread_mu_{mu}.sdf"
        make_world(world, mu, gx, gy, case_pitch_deg, bread_x, bread_y)
        subprocess.check_call([GZ, "sdf", "-k", str(world)], stdout=subprocess.DEVNULL)
        proc = subprocess.Popen(
            [GZ, "sim", "-r", "-s", str(world)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
            env=os.environ.copy(),
        )
        try:
            start_deadline = time.time() + 7.0
            p0 = None
            while time.time() < start_deadline:
                p0 = sample_pose("bread_probe", 1.0)
                if p0 is not None:
                    break
                time.sleep(0.2)
            if p0 is None:
                return {"mu": mu, "error": "pose topic unavailable"}
            time.sleep(duration_sec)
            p1 = sample_pose("bread_probe", 2.0)
            if p1 is None:
                return {"mu": mu, "error": "final pose unavailable", "p0": p0}
            dx, dy, dz = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            planar = (dx * dx + dy * dy) ** 0.5
            return {
                "mu": mu,
                "error": "",
                "p0": p0,
                "p1": p1,
                "dx": dx,
                "dy": dy,
                "dz": dz,
                "planar": planar,
            }
        finally:
            terminate(proc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gx", type=float, default=2.0)
    parser.add_argument("--gy", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mu", type=float, nargs="+", default=[0.01, 0.2, 1.0, 10.0, 100.0])
    parser.add_argument("--case-pitch-deg", type=float, default=0.0)
    parser.add_argument("--bread-x", type=float, default=0.0)
    parser.add_argument("--bread-y", type=float, default=0.0)
    args = parser.parse_args()

    threshold = (args.gx * args.gx + args.gy * args.gy) ** 0.5 / 9.81
    print(f"case/bread contact; horizontal gravity threshold estimate mu > {threshold:.3f}")
    rows = []
    for mu in args.mu:
        for run_idx in range(args.runs):
            row = run_once(mu, args.gx, args.gy, args.duration, args.case_pitch_deg, args.bread_x, args.bread_y)
            row["run"] = run_idx + 1
            rows.append(row)
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    print("summary:")
    for mu in args.mu:
        subset = [row for row in rows if row.get("mu") == mu and not row.get("error")]
        if not subset:
            print(f"  mu={mu}: no valid runs")
            continue
        planars = [float(row["planar"]) for row in subset]
        print(f"  mu={mu}: planar min/avg/max = {min(planars):.4f}/{sum(planars)/len(planars):.4f}/{max(planars):.4f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
