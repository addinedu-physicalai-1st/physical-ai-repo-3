#!/usr/bin/env python3
"""Load exported Gazebo layout collision boxes into MoveIt planning scene."""

from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Pose
from moveit_msgs.msg import CollisionObject, PlanningScene
from moveit_msgs.srv import ApplyPlanningScene
from rclpy.node import Node
from shape_msgs.msg import SolidPrimitive


def parse_floats(value: str | None, expected: int) -> list[float]:
    if value is None:
        return [0.0] * expected
    parts = [float(part) for part in value.split()]
    if len(parts) != expected:
        raise ValueError(f"expected {expected} floats, got {len(parts)}: {value}")
    return parts


def quaternion_from_rpy(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def quaternion_multiply(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def rotate_vector(
    q: tuple[float, float, float, float],
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    qv = (v[0], v[1], v[2], 0.0)
    q_conj = (-q[0], -q[1], -q[2], q[3])
    result = quaternion_multiply(quaternion_multiply(q, qv), q_conj)
    return result[:3]


def composed_pose(
    model_xyz: list[float],
    model_rpy: list[float],
    local_xyz: list[float],
    local_rpy: list[float],
) -> Pose:
    model_q = quaternion_from_rpy(*model_rpy)
    local_q = quaternion_from_rpy(*local_rpy)
    rotated = rotate_vector(model_q, (local_xyz[0], local_xyz[1], local_xyz[2]))
    q = quaternion_multiply(model_q, local_q)

    pose = Pose()
    pose.position.x = model_xyz[0] + rotated[0]
    pose.position.y = model_xyz[1] + rotated[1]
    pose.position.z = model_xyz[2] + rotated[2]
    pose.orientation.x = q[0]
    pose.orientation.y = q[1]
    pose.orientation.z = q[2]
    pose.orientation.w = q[3]
    return pose


class PlanningSceneLayoutSync(Node):
    def __init__(self) -> None:
        super().__init__("planning_scene_layout_sync")
        package_share = Path(get_package_share_directory("ddooby_controller"))
        default_layout = str(package_share / "assets" / "manufacturing_world" / "layout.json")

        self.declare_parameter("layout_path", default_layout)
        self.declare_parameter("frame_id", "world")
        self.declare_parameter("include_collections", ["Environment", "Object"])
        self.declare_parameter("apply_service", "/apply_planning_scene")
        self.declare_parameter("wait_timeout_sec", 60.0)

    def run(self) -> int:
        layout_path = Path(self.get_parameter("layout_path").value)
        frame_id = str(self.get_parameter("frame_id").value)
        include_collections = set(self.get_parameter("include_collections").value)
        service_name = str(self.get_parameter("apply_service").value)
        wait_timeout = float(self.get_parameter("wait_timeout_sec").value)

        objects = self.load_collision_objects(layout_path, frame_id, include_collections)
        if not objects:
            self.get_logger().warn(f"no collision objects loaded from {layout_path}")
            return 1

        client = self.create_client(ApplyPlanningScene, service_name)
        self.get_logger().info(f"waiting for {service_name}")
        if not client.wait_for_service(timeout_sec=wait_timeout):
            self.get_logger().error(f"{service_name} not available after {wait_timeout:.1f}s")
            return 2

        scene = PlanningScene()
        scene.is_diff = True
        scene.world.collision_objects = objects

        request = ApplyPlanningScene.Request()
        request.scene = scene
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self, future)
        result = future.result()
        if result is None:
            self.get_logger().error("failed to call apply planning scene service")
            return 3
        if not result.success:
            self.get_logger().error("MoveIt rejected planning scene update")
            return 4

        primitive_count = sum(len(obj.primitives) for obj in objects)
        self.get_logger().info(
            f"applied {len(objects)} collision objects / {primitive_count} boxes to MoveIt planning scene"
        )
        return 0

    def load_collision_objects(
        self,
        layout_path: Path,
        frame_id: str,
        include_collections: set[str],
    ) -> list[CollisionObject]:
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        package_share = layout_path.parents[1]
        collision_objects: list[CollisionObject] = []

        for model in layout["models"]:
            collection = model.get("collection", "")
            if collection not in include_collections:
                continue

            model_dir = package_share / model["model_dir"]
            model_sdf = model_dir / "model.sdf"
            collision_object = self.collision_object_from_sdf(
                model["name"],
                model_sdf,
                model["xyz"],
                model["rpy"],
                frame_id,
            )
            if collision_object.primitives:
                collision_objects.append(collision_object)

        return collision_objects

    def collision_object_from_sdf(
        self,
        model_name: str,
        model_sdf: Path,
        model_xyz: list[float],
        model_rpy: list[float],
        frame_id: str,
    ) -> CollisionObject:
        root = ET.parse(model_sdf).getroot()
        collision_object = CollisionObject()
        collision_object.header.frame_id = frame_id
        collision_object.id = model_name
        collision_object.operation = CollisionObject.ADD

        for collision in root.findall(".//collision"):
            box = collision.find("./geometry/box")
            if box is None:
                continue

            local_pose = parse_floats(collision.findtext("pose"), 6)
            size = parse_floats(box.findtext("size"), 3)

            primitive = SolidPrimitive()
            primitive.type = SolidPrimitive.BOX
            primitive.dimensions = [0.0, 0.0, 0.0]
            primitive.dimensions[SolidPrimitive.BOX_X] = size[0]
            primitive.dimensions[SolidPrimitive.BOX_Y] = size[1]
            primitive.dimensions[SolidPrimitive.BOX_Z] = size[2]

            pose = composed_pose(
                model_xyz,
                model_rpy,
                local_pose[:3],
                local_pose[3:],
            )
            collision_object.primitives.append(primitive)
            collision_object.primitive_poses.append(pose)

        return collision_object


def main() -> None:
    rclpy.init()
    node = PlanningSceneLayoutSync()
    try:
        exit_code = node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
