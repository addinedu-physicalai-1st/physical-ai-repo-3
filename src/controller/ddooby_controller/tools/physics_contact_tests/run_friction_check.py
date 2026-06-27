#!/usr/bin/env python3
"""Check whether Gazebo applies SDF surface friction values in a minimal world.

The test uses a horizontal floor with a tilted gravity vector. In an ideal Coulomb
model, a block should slide when mu < |gx/gz| and remain close to its start when
mu > |gx/gz|. We run Gazebo headless and read /world/default/pose/info, so this
is numeric and repeatable instead of visual inspection.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
import shutil
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
GZ = shutil.which("gz") or "/opt/ros/jazzy/bin/gz"
WORLD_TEMPLATE = """<?xml version=\"1.0\"?>
<sdf version=\"1.9\">
  <world name=\"default\">
    <gravity>{gx} 0 -9.81</gravity>
    <physics name=\"friction_probe_physics\" default=\"true\" type=\"ignored\">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>1000</real_time_update_rate>
      <max_contacts>20</max_contacts>
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

    <model name=\"floor\">
      <static>true</static>
      <pose>0 0 0 0 0 0</pose>
      <link name=\"link\">
        <collision name=\"collision\">
          <geometry><box><size>5 5 0.05</size></box></geometry>
          <surface>
            <friction><ode><mu>{floor_mu}</mu><mu2>{floor_mu}</mu2></ode></friction>
            <contact><ode><kp>1000000</kp><kd>100</kd><max_vel>0.01</max_vel><min_depth>0.001</min_depth></ode></contact>
          </surface>
        </collision>
        <visual name=\"visual\"><geometry><box><size>5 5 0.05</size></box></geometry></visual>
      </link>
    </model>

    <model name=\"test_block\">
      <pose>0 0 0.075 0 0 0</pose>
      <link name=\"link\">
        <inertial>
          <mass>0.05</mass>
          <inertia><ixx>0.000083</ixx><iyy>0.000083</iyy><izz>0.000083</izz></inertia>
        </inertial>
        <collision name=\"collision\">
          <geometry><box><size>0.1 0.1 0.1</size></box></geometry>
          <surface>
            <friction><ode><mu>{block_mu}</mu><mu2>{block_mu}</mu2></ode></friction>
            <contact><ode><kp>1000000</kp><kd>100</kd><max_vel>0.01</max_vel><min_depth>0.001</min_depth></ode></contact>
          </surface>
        </collision>
        <visual name=\"visual\"><geometry><box><size>0.1 0.1 0.1</size></box></geometry></visual>
      </link>
    </model>
  </world>
</sdf>
"""


def make_world(path: Path, mu: float, gx: float) -> None:
    path.write_text(WORLD_TEMPLATE.format(gx=gx, floor_mu=mu, block_mu=mu), encoding="utf-8")


def extract_block_x(text: str) -> float | None:
    # Works with protobuf text output from gz topic -e.
    model_blocks = re.finditer(r'name:\s*"test_block"(?P<body>.*?)(?=\nname:\s*"|$)', text, flags=re.S)
    for match in model_blocks:
        body = match.group('body')
        pose_match = re.search(r'position\s*\{(?P<pos>.*?)\}', body, flags=re.S)
        if not pose_match:
            continue
        x_match = re.search(r'\bx:\s*([-+0-9.eE]+)', pose_match.group('pos'))
        if x_match:
            return float(x_match.group(1))
    return None


def sample_pose(timeout_sec: float = 2.0) -> float | None:
    cmd = [GZ, "topic", "-e", "-t", "/world/default/pose/info", "-n", "1"]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout_sec)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return extract_block_x(out)


def run_case(mu: float, gx: float, duration_sec: float) -> dict[str, float | str | None]:
    with tempfile.TemporaryDirectory(prefix="ddooby_friction_") as tmp:
        world = Path(tmp) / f"friction_mu_{mu}.sdf"
        make_world(world, mu, gx)
        subprocess.check_call([GZ, "sdf", "-k", str(world)], stdout=subprocess.DEVNULL)
        env = os.environ.copy()
        proc = subprocess.Popen(
            [GZ, "sim", "-r", "-s", str(world)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
            env=env,
        )
        try:
            start_deadline = time.time() + 6.0
            x0 = None
            while time.time() < start_deadline:
                x0 = sample_pose(1.0)
                if x0 is not None:
                    break
                time.sleep(0.2)
            if x0 is None:
                return {"mu": mu, "error": "pose topic unavailable", "x0": None, "x1": None, "dx": None}
            time.sleep(duration_sec)
            x1 = sample_pose(2.0)
            if x1 is None:
                return {"mu": mu, "error": "final pose unavailable", "x0": x0, "x1": None, "dx": None}
            return {"mu": mu, "error": "", "x0": x0, "x1": x1, "dx": x1 - x0}
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=3.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gx", type=float, default=2.0, help="Horizontal gravity component. Threshold mu ~= gx / 9.81")
    parser.add_argument("--duration", type=float, default=4.0)
    parser.add_argument("--mu", type=float, nargs="+", default=[0.01, 0.2, 1.0, 10.0, 100.0])
    args = parser.parse_args()

    threshold = abs(args.gx / 9.81)
    print(f"friction threshold estimate: mu > {threshold:.3f} should resist sliding")
    rows = [run_case(mu, args.gx, args.duration) for mu in args.mu]
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    print("summary:")
    for row in rows:
        if row.get("error"):
            print(f"  mu={row['mu']}: ERROR {row['error']}")
            continue
        dx = float(row["dx"])
        print(f"  mu={row['mu']}: dx={dx:+.4f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
