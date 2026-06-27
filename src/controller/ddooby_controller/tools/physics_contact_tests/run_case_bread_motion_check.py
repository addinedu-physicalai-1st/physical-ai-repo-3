#!/usr/bin/env python3
"""Move the exported case under bread and measure relative slip/drop.

This test uses the real exported case and bread SDF collision geometry. The case
is moved kinematically through Gazebo's set_pose service while bread remains a
dynamic body. It is intended to distinguish static friction problems from
dynamic transport / contact-break problems.
"""

from __future__ import annotations

import argparse
import json
import math
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

WORLD_TEMPLATE = """<?xml version="1.0"?>
<sdf version="1.9">
  <world name="default">
    <gravity>0 0 -9.81</gravity>
    <physics name="case_bread_motion_physics" default="true" type="ignored">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>1000</real_time_update_rate>
      <max_contacts>160</max_contacts>
      <dart>
        <collision_detector>ode</collision_detector>
        <solver>
          <solver_type>dantzig</solver_type>
        </solver>
      </dart>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-apply-link-wrench-system" name="gz::sim::systems::ApplyLinkWrench"/>

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
    return re.sub(r"\n\s*<visual\b.*?</visual>", "", block, flags=re.S)


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


def quat_from_rpy(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    return x, y, z, w


def make_world(
    path: Path,
    mu: float,
    case_pitch_deg: float,
    bread_x: float,
    bread_y: float,
    case_static: bool,
) -> None:
    case = set_model_name(model_block("case"), "case", "case_probe")
    bread = set_model_name(model_block("bread1"), "bread1", "bread_probe")
    case = set_mu(case, mu)
    bread = set_mu(bread, mu)
    if not case_static:
        slide_joint = """
    <joint name="case_slide_x" type="prismatic">
      <parent>world</parent>
      <child>case_probe_link</child>
      <axis>
        <xyz>1 0 0</xyz>
        <limit>
          <lower>-1.0</lower>
          <upper>1.0</upper>
          <effort>100</effort>
          <velocity>1.0</velocity>
        </limit>
        <dynamics>
          <damping>0.02</damping>
          <friction>0.0</friction>
        </dynamics>
      </axis>
    </joint>
    <plugin filename="gz-sim-joint-controller-system" name="gz::sim::systems::JointController">
      <joint_name>case_slide_x</joint_name>
      <initial_velocity>0.0</initial_velocity>
    </plugin>
"""
        case = re.sub(r"\n\s*</model>", slide_joint + "  </model>", case, count=1)

    case_pitch = math.radians(case_pitch_deg)
    case_z = 0.050
    bread_z = case_z + 0.0032
    case = set_static_and_pose(case, case_static, f"0 0 {case_z:.6f} 0 {case_pitch:.9f} 0")
    bread = set_static_and_pose(bread, False, f"{bread_x:.6f} {bread_y:.6f} {bread_z:.6f} 0 0 0")
    path.write_text(WORLD_TEMPLATE.format(case_model=case, bread_model=bread), encoding="utf-8")


def extract_pose(text: str, model_name: str) -> tuple[float, float, float] | None:
    pattern = rf'name:\s*"{re.escape(model_name)}"(?P<body>.*?)(?=\nname:\s*"|$)'
    for match in re.finditer(pattern, text, flags=re.S):
        pose_match = re.search(r"position\s*\{(?P<pos>.*?)\}", match.group("body"), flags=re.S)
        if not pose_match:
            continue
        pos = pose_match.group("pos")
        values: list[float] = []
        for axis in ("x", "y", "z"):
            axis_match = re.search(rf"\b{axis}:\s*([-+0-9.eE]+)", pos)
            values.append(float(axis_match.group(1)) if axis_match else 0.0)
        return values[0], values[1], values[2]
    return None


def sample_pose(model_name: str, timeout_sec: float = 1.0) -> tuple[float, float, float] | None:
    try:
        out = subprocess.check_output(
            [GZ, "topic", "-e", "-t", "/world/default/pose/info", "-n", "1"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout_sec,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return extract_pose(out, model_name)


def set_case_pose(x: float, y: float, z: float, pitch_rad: float) -> bool:
    qx, qy, qz, qw = quat_from_rpy(0.0, pitch_rad, 0.0)
    req = (
        'name: "case_probe" '
        f"position {{ x: {x:.9f} y: {y:.9f} z: {z:.9f} }} "
        f"orientation {{ x: {qx:.9f} y: {qy:.9f} z: {qz:.9f} w: {qw:.9f} }}"
    )
    result = subprocess.run(
        [
            GZ,
            "service",
            "-s",
            "/world/default/set_pose",
            "--reqtype",
            "gz.msgs.Pose",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            "1000",
            "--req",
            req,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
    )
    return result.returncode == 0 and "data: true" in result.stdout


def command_case_joint_velocity(velocity: float) -> bool:
    result = subprocess.run(
        [
            GZ,
            "topic",
            "-t",
            "/model/case_probe/joint/case_slide_x/cmd_vel",
            "-m",
            "gz.msgs.Double",
            "-p",
            f"data: {velocity:.9f}",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1.0,
    )
    return result.returncode == 0


def apply_case_wrench(force_x: float, force_y: float, force_z: float = 0.0) -> bool:
    req = (
        'entity { name: "case_probe::case_probe_link" type: LINK } '
        "wrench { "
        f"force {{ x: {force_x:.9f} y: {force_y:.9f} z: {force_z:.9f} }} "
        "torque { x: 0 y: 0 z: 0 } "
        "}"
    )
    result = subprocess.run(
        [GZ, "topic", "-t", "/world/default/wrench/persistent", "-m", "gz.msgs.EntityWrench", "-p", req],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1.0,
    )
    return result.returncode == 0


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


def smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def run_once(args: argparse.Namespace) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ddooby_case_bread_motion_") as tmp:
        world = Path(tmp) / "case_bread_motion.sdf"
        make_world(
            world,
            args.mu,
            args.case_pitch_deg,
            args.bread_x,
            args.bread_y,
            case_static=args.mode == "set_pose",
        )
        subprocess.check_call([GZ, "sdf", "-k", str(world)], stdout=subprocess.DEVNULL)
        log_path = Path(tmp) / "gz_sim.log"
        log_file = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [GZ, "sim", "-r", "-s", str(world)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
            env=os.environ.copy(),
        )
        try:
            deadline = time.time() + 7.0
            initial_bread = None
            while time.time() < deadline:
                initial_bread = sample_pose("bread_probe", 1.0)
                if initial_bread is not None:
                    break
                time.sleep(0.1)
            if initial_bread is None:
                return {"error": "pose topic unavailable"}

            initial_case = sample_pose("case_probe", 1.0)
            if initial_case is None:
                return {"error": "initial case pose unavailable"}

            start = time.monotonic()
            pitch = math.radians(args.case_pitch_deg)
            case_z = 0.050
            case_final = initial_case
            persistent_wrench_sent = False
            max_rel = 0.0
            min_rel_z = 999.0
            max_rel_z = -999.0
            samples = 0
            while True:
                elapsed = time.monotonic() - start
                t = min(1.0, elapsed / args.move_duration)
                if args.mode == "set_pose":
                    f = smoothstep(t) if args.profile == "smoothstep" else t
                    case_x = args.move_x * f
                    case_y = args.move_y * f
                    ok = set_case_pose(case_x, case_y, case_z, pitch)
                    if not ok:
                        return {"error": "set_pose failed", "elapsed": elapsed}
                    case = (case_x, case_y, case_z)
                elif args.mode == "force":
                    if not persistent_wrench_sent:
                        ok = apply_case_wrench(args.force_x, args.force_y, args.force_z)
                        if not ok:
                            return {"error": "apply wrench failed", "elapsed": elapsed}
                        persistent_wrench_sent = True
                    sampled_case = sample_pose("case_probe", 0.5)
                    case = sampled_case if sampled_case is not None else case_final
                else:
                    ok = command_case_joint_velocity(args.joint_velocity)
                    if not ok:
                        return {"error": "joint velocity command failed", "elapsed": elapsed}
                    sampled_case = sample_pose("case_probe", 0.5)
                    case = sampled_case if sampled_case is not None else case_final
                time.sleep(args.command_period)
                bread = sample_pose("bread_probe", 0.5)
                if bread is not None:
                    rel_x = bread[0] - case[0]
                    rel_y = bread[1] - case[1]
                    rel_z = bread[2] - case[2]
                    planar = math.hypot(rel_x - args.bread_x, rel_y - args.bread_y)
                    max_rel = max(max_rel, planar)
                    min_rel_z = min(min_rel_z, rel_z)
                    max_rel_z = max(max_rel_z, rel_z)
                    samples += 1
                case_final = case
                if t >= 1.0:
                    break
            if args.mode == "joint_velocity":
                command_case_joint_velocity(0.0)
            time.sleep(args.settle_duration)
            final_case_sample = sample_pose("case_probe", 2.0)
            if final_case_sample is not None:
                case_final = final_case_sample
            final_bread = sample_pose("bread_probe", 2.0)
            if final_bread is None:
                return {"error": "final pose unavailable"}
            final_rel = (
                final_bread[0] - case_final[0],
                final_bread[1] - case_final[1],
                final_bread[2] - case_final[2],
            )
            final_planar = math.hypot(final_rel[0] - args.bread_x, final_rel[1] - args.bread_y)
            return {
                "error": "",
                "mu": args.mu,
                "move": [args.move_x, args.move_y],
                "force": [args.force_x, args.force_y, args.force_z],
                "mode": args.mode,
                "move_duration": args.move_duration,
                "profile": args.profile,
                "case_pitch_deg": args.case_pitch_deg,
                "initial_bread": initial_bread,
                "final_bread": final_bread,
                "final_case": case_final,
                "final_rel": final_rel,
                "final_planar_slip": final_planar,
                "max_planar_slip": max_rel,
                "min_rel_z": min_rel_z,
                "max_rel_z": max_rel_z,
                "samples": samples,
                "pass": final_planar < args.max_slip and final_rel[2] > args.min_rel_z,
            }
        finally:
            terminate(proc)
            try:
                log_file.close()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mu", type=float, default=10.0)
    parser.add_argument("--move-x", type=float, default=0.20)
    parser.add_argument("--move-y", type=float, default=0.00)
    parser.add_argument("--force-x", type=float, default=0.02)
    parser.add_argument("--force-y", type=float, default=0.00)
    parser.add_argument("--force-z", type=float, default=0.0)
    parser.add_argument("--joint-velocity", type=float, default=0.05)
    parser.add_argument("--move-duration", type=float, default=2.0)
    parser.add_argument("--settle-duration", type=float, default=0.5)
    parser.add_argument("--command-period", type=float, default=0.05)
    parser.add_argument("--profile", choices=["smoothstep", "linear"], default="smoothstep")
    parser.add_argument("--mode", choices=["set_pose", "force", "joint_velocity"], default="joint_velocity")
    parser.add_argument("--case-pitch-deg", type=float, default=0.0)
    parser.add_argument("--bread-x", type=float, default=0.0)
    parser.add_argument("--bread-y", type=float, default=0.0)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-slip", type=float, default=0.015)
    parser.add_argument("--min-rel-z", type=float, default=-0.020)
    args = parser.parse_args()

    rows = []
    for idx in range(args.runs):
        row = run_once(args)
        row["run"] = idx + 1
        rows.append(row)
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    valid = [row for row in rows if not row.get("error")]
    if valid:
        slips = [float(row["final_planar_slip"]) for row in valid]
        max_slips = [float(row["max_planar_slip"]) for row in valid]
        passes = sum(1 for row in valid if row.get("pass"))
        print(
            "summary: "
            f"pass={passes}/{len(valid)}, "
            f"final_slip min/avg/max={min(slips):.4f}/{sum(slips)/len(slips):.4f}/{max(slips):.4f} m, "
            f"max_slip max={max(max_slips):.4f} m"
        )
    return 0 if all(row.get("pass") for row in valid) and len(valid) == args.runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
