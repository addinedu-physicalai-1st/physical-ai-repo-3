#!/usr/bin/env python3

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Pose, PoseArray, TransformStamped
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import Header
import tf2_ros
from vision_msgs.msg import (
    BoundingBox3D,
    Detection3D,
    Detection3DArray,
    ObjectHypothesisWithPose,
)

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


@dataclass
class PcaResult:
    centroid: np.ndarray
    axes: np.ndarray
    extents: np.ndarray


@dataclass
class DetectionPose:
    class_name: str
    score: float
    bbox_xyxy: tuple[int, int, int, int]
    centroid_source: np.ndarray
    axes_source: np.ndarray
    extents: np.ndarray
    centroid_target: np.ndarray
    axes_target: np.ndarray
    orientation_xyzw: np.ndarray
    entry_position: np.ndarray
    layout_name: str = ""
    layout_distance_m: float = math.nan


@dataclass
class HsvDetectionRule:
    class_name: str
    ranges: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]
    score: float


@dataclass
class LayoutObject:
    name: str
    class_name: str
    position: np.ndarray


def normalize(vector: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < 1e-9:
        return fallback.astype(float)
    return vector / norm


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def default_layout_path() -> str:
    try:
        return str(
            Path(get_package_share_directory("ddooby_controller"))
            / "assets"
            / "manufacturing_world"
            / "layout.json"
        )
    except Exception:
        return ""


def layout_class_from_model_name(name: str) -> str | None:
    normalized = name.strip().lower()
    if normalized.startswith("can_coke"):
        return "coke"
    if normalized.startswith("can_coffee"):
        return "coffee"
    if normalized in ("kachup", "ketchup") or normalized.startswith("kachup"):
        return "ketchup"
    if normalized.startswith("case"):
        return "case"
    if normalized.startswith("bread") and "tray" not in normalized:
        return "bread"
    if normalized.startswith("sausage") and "tray" not in normalized:
        return "sausage"
    return None


def class_matches_layout(detection_class: str, layout_class: str) -> bool:
    detection_class = detection_class.strip().lower()
    layout_class = layout_class.strip().lower()
    if detection_class == layout_class:
        return True
    aliases = {
        "ketchup": {"ketchup", "kachup", "red_object", "bottle"},
        "coke": {"coke", "can_coke", "red_object", "can"},
        "coffee": {"coffee", "can_coffee", "can"},
    }
    return detection_class in aliases.get(layout_class, set())


def quaternion_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-12:
        return np.eye(3)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=float,
    )


def matrix_to_quaternion(rotation: np.ndarray) -> np.ndarray:
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        w = (rotation[2, 1] - rotation[1, 2]) / scale
        x = 0.25 * scale
        y = (rotation[0, 1] + rotation[1, 0]) / scale
        z = (rotation[0, 2] + rotation[2, 0]) / scale
    elif rotation[1, 1] > rotation[2, 2]:
        scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        w = (rotation[0, 2] - rotation[2, 0]) / scale
        x = (rotation[0, 1] + rotation[1, 0]) / scale
        y = 0.25 * scale
        z = (rotation[1, 2] + rotation[2, 1]) / scale
    else:
        scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        w = (rotation[1, 0] - rotation[0, 1]) / scale
        x = (rotation[0, 2] + rotation[2, 0]) / scale
        y = (rotation[1, 2] + rotation[2, 1]) / scale
        z = 0.25 * scale
    quat = np.array([x, y, z, w], dtype=float)
    return normalize(quat, np.array([0.0, 0.0, 0.0, 1.0], dtype=float))


def axes_to_quaternion(long_axis: np.ndarray, view_axis: np.ndarray) -> np.ndarray:
    x_axis = normalize(long_axis, np.array([1.0, 0.0, 0.0], dtype=float))
    z_hint = normalize(view_axis, np.array([0.0, 0.0, 1.0], dtype=float))
    y_axis = np.cross(z_hint, x_axis)
    if np.linalg.norm(y_axis) < 1e-6:
        y_axis = np.cross(np.array([0.0, 1.0, 0.0], dtype=float), x_axis)
    y_axis = normalize(y_axis, np.array([0.0, 1.0, 0.0], dtype=float))
    z_axis = normalize(np.cross(x_axis, y_axis), np.array([0.0, 0.0, 1.0], dtype=float))
    rotation = np.column_stack([x_axis, y_axis, z_axis])
    return matrix_to_quaternion(rotation)


def deproject(u: np.ndarray, v: np.ndarray, z: np.ndarray, camera_info: CameraInfo) -> np.ndarray:
    fx = camera_info.k[0]
    fy = camera_info.k[4]
    cx = camera_info.k[2]
    cy = camera_info.k[5]
    x = (u - cx) * z / fx
    y = (v - cy) * z / fy
    return np.column_stack([x, y, z])


def depth_to_meters(depth_image: np.ndarray, encoding: str, depth_scale: float) -> np.ndarray:
    if encoding == "32FC1":
        return depth_image.astype(np.float32)
    if encoding in ("16UC1", "mono16"):
        return depth_image.astype(np.float32) * float(depth_scale)
    return depth_image.astype(np.float32)


def pca_from_points(points: np.ndarray) -> PcaResult | None:
    if points.shape[0] < 8:
        return None

    centroid = np.median(points, axis=0)
    centered = points - centroid
    distances = np.linalg.norm(centered, axis=1)
    keep = distances <= np.percentile(distances, 85.0)
    filtered = points[keep]
    if filtered.shape[0] < 8:
        filtered = points

    centroid = np.mean(filtered, axis=0)
    centered = filtered - centroid
    covariance = np.cov(centered, rowvar=False)
    values, vectors = np.linalg.eigh(covariance)
    order = np.argsort(values)[::-1]
    axes = vectors[:, order]

    if axes[0, 0] < 0.0:
        axes[:, 0] *= -1.0
    if np.linalg.det(axes) < 0.0:
        axes[:, 2] *= -1.0

    projected = centered @ axes
    extents = np.max(projected, axis=0) - np.min(projected, axis=0)
    return PcaResult(centroid=centroid, axes=axes, extents=extents)


def transform_points(points: np.ndarray, transform: TransformStamped | None) -> np.ndarray:
    if transform is None:
        return points
    translation = transform.transform.translation
    rotation = transform.transform.rotation
    matrix = quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
    offset = np.array([translation.x, translation.y, translation.z], dtype=float)
    return (matrix @ points.T).T + offset


def transform_axes(axes: np.ndarray, transform: TransformStamped | None) -> np.ndarray:
    if transform is None:
        return axes
    rotation = transform.transform.rotation
    matrix = quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
    return matrix @ axes


def make_pose(position: np.ndarray, quat_xyzw: np.ndarray) -> Pose:
    pose = Pose()
    pose.position.x = float(position[0])
    pose.position.y = float(position[1])
    pose.position.z = float(position[2])
    pose.orientation.x = float(quat_xyzw[0])
    pose.orientation.y = float(quat_xyzw[1])
    pose.orientation.z = float(quat_xyzw[2])
    pose.orientation.w = float(quat_xyzw[3])
    return pose


HSV_RULES = (
    HsvDetectionRule(
        "sausage",
        (((5, 90, 70), (24, 255, 255)),),
        0.90,
    ),
    HsvDetectionRule(
        "bread",
        (((20, 45, 70), (45, 255, 255)),),
        0.82,
    ),
    HsvDetectionRule(
        "coffee",
        (((5, 45, 20), (28, 255, 145)),),
        0.88,
    ),
    HsvDetectionRule(
        "case",
        (((0, 0, 145), (180, 45, 255)),),
        0.78,
    ),
    HsvDetectionRule(
        "red_object",
        (((0, 70, 45), (9, 255, 255)), ((170, 70, 45), (180, 255, 255))),
        0.86,
    ),
)


class GazeboYoloPoseNode(Node):
    def __init__(self):
        super().__init__("gazebo_yolo_pose")

        self.declare_parameter("detector_backend", "hsv")
        self.declare_parameter("model_path", "yolo11n.pt")
        self.declare_parameter("conf_threshold", 0.35)
        self.declare_parameter("iou_threshold", 0.45)
        self.declare_parameter("color_topic", "/realsense_d435/image")
        self.declare_parameter("depth_topic", "/realsense_d435/depth_image")
        self.declare_parameter("camera_info_topic", "/realsense_d435/camera_info")
        self.declare_parameter("camera_frame_fallback", "realsense_d435_color_optical_frame")
        self.declare_parameter("target_frame", "world")
        self.declare_parameter("detections_topic", "/manufacturing_vision/detections")
        self.declare_parameter("grasp_pose_topic", "/manufacturing_vision/grasp_entry_poses")
        self.declare_parameter("debug_image_topic", "/manufacturing_vision/debug_image")
        self.declare_parameter("class_allowlist", [])
        self.declare_parameter("depth_scale", 0.001)
        self.declare_parameter("min_depth_m", 0.05)
        self.declare_parameter("max_depth_m", 3.0)
        self.declare_parameter("roi_stride", 4)
        self.declare_parameter("grasp_entry_distance_m", 0.08)
        self.declare_parameter("process_every_n", 1)
        self.declare_parameter("publish_debug_image", True)
        self.declare_parameter("show_debug_view", False)
        self.declare_parameter("debug_window_name", "manufacturing_vision")
        self.declare_parameter("hsv_min_area_px", 120)
        self.declare_parameter("hsv_min_fill_ratio", 0.18)
        self.declare_parameter("hsv_max_area_fraction", 0.20)
        self.declare_parameter("hsv_morph_kernel", 5)
        self.declare_parameter("hsv_red_ketchup_min_extent_m", 0.18)
        self.declare_parameter("layout_path", default_layout_path())
        self.declare_parameter("enable_layout_matching", True)
        self.declare_parameter("layout_match_max_distance_m", 0.18)
        self.declare_parameter("layout_pose_weight", 0.85)
        self.declare_parameter("layout_match_publish_unmatched", False)

        self._bridge = CvBridge()
        self._depth_image = None
        self._depth_encoding = ""
        self._camera_info = None
        self._frame_count = 0

        self._detector_backend = str(self.get_parameter("detector_backend").value).strip().lower()
        if self._detector_backend not in ("hsv", "yolo"):
            raise ValueError("detector_backend must be 'hsv' or 'yolo'")
        self._model_path = str(self.get_parameter("model_path").value)
        self._conf = float(self.get_parameter("conf_threshold").value)
        self._iou = float(self.get_parameter("iou_threshold").value)
        self._target_frame = str(self.get_parameter("target_frame").value)
        self._camera_frame_fallback = str(self.get_parameter("camera_frame_fallback").value)
        self._depth_scale = float(self.get_parameter("depth_scale").value)
        self._min_depth = float(self.get_parameter("min_depth_m").value)
        self._max_depth = float(self.get_parameter("max_depth_m").value)
        self._roi_stride = max(1, int(self.get_parameter("roi_stride").value))
        self._entry_distance = float(self.get_parameter("grasp_entry_distance_m").value)
        self._process_every_n = max(1, int(self.get_parameter("process_every_n").value))
        self._publish_debug_image = as_bool(self.get_parameter("publish_debug_image").value)
        self._show_debug_view = as_bool(self.get_parameter("show_debug_view").value)
        self._debug_window_name = str(self.get_parameter("debug_window_name").value)
        self._hsv_min_area_px = max(1, int(self.get_parameter("hsv_min_area_px").value))
        self._hsv_min_fill_ratio = float(self.get_parameter("hsv_min_fill_ratio").value)
        self._hsv_max_area_fraction = float(self.get_parameter("hsv_max_area_fraction").value)
        self._hsv_morph_kernel = max(1, int(self.get_parameter("hsv_morph_kernel").value))
        self._hsv_red_ketchup_min_extent_m = float(self.get_parameter("hsv_red_ketchup_min_extent_m").value)
        self._layout_path = str(self.get_parameter("layout_path").value)
        self._enable_layout_matching = as_bool(self.get_parameter("enable_layout_matching").value)
        self._layout_match_max_distance = float(self.get_parameter("layout_match_max_distance_m").value)
        self._layout_pose_weight = float(np.clip(float(self.get_parameter("layout_pose_weight").value), 0.0, 1.0))
        self._layout_match_publish_unmatched = as_bool(
            self.get_parameter("layout_match_publish_unmatched").value
        )
        self._layout_objects = self._load_layout_objects(Path(self._layout_path)) if self._layout_path else []
        self._last_raw_detection_count = 0
        self._debug_window_created = False
        self._last_ui_time = time.monotonic()
        self._ui_fps = 0.0
        self._class_allowlist = {
            str(item).strip()
            for item in self.get_parameter("class_allowlist").value
            if str(item).strip()
        }

        detections_topic = str(self.get_parameter("detections_topic").value)
        grasp_pose_topic = str(self.get_parameter("grasp_pose_topic").value)
        debug_image_topic = str(self.get_parameter("debug_image_topic").value)

        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)
        self._model = None
        if self._detector_backend == "yolo":
            if YOLO is None:
                raise RuntimeError("ultralytics is not installed; install it before running YOLO perception")
            self._model = YOLO(self._model_path)

        self._detections_pub = self.create_publisher(Detection3DArray, detections_topic, 10)
        self._grasp_pose_pub = self.create_publisher(PoseArray, grasp_pose_topic, 10)
        self._debug_image_pub = self.create_publisher(Image, debug_image_topic, 10)

        self.create_subscription(
            CameraInfo,
            str(self.get_parameter("camera_info_topic").value),
            self._on_camera_info,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Image,
            str(self.get_parameter("depth_topic").value),
            self._on_depth,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Image,
            str(self.get_parameter("color_topic").value),
            self._on_color,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            f"Gazebo vision pose node ready: backend={self._detector_backend}, "
            f"model={self._model_path if self._detector_backend == 'yolo' else 'unused'}, "
            f"target_frame={self._target_frame}, "
            f"layout_matching={self._enable_layout_matching}, layout_objects={len(self._layout_objects)}"
        )

    def _on_camera_info(self, msg: CameraInfo) -> None:
        self._camera_info = msg

    def _on_depth(self, msg: Image) -> None:
        self._depth_image = self._bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        self._depth_encoding = msg.encoding

    def _lookup_transform(self, source_frame: str) -> TransformStamped | None:
        if not self._target_frame or self._target_frame == source_frame:
            return None
        try:
            return self._tf_buffer.lookup_transform(
                self._target_frame,
                source_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.05),
            )
        except Exception as exc:
            self.get_logger().warn(
                f"Using camera frame because TF {source_frame}->{self._target_frame} is unavailable: {exc}",
                throttle_duration_sec=2.0,
            )
            return None

    def _on_color(self, msg: Image) -> None:
        if self._depth_image is None or self._camera_info is None:
            return

        self._frame_count += 1
        if self._frame_count % self._process_every_n != 0:
            return

        color = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        depth_m = depth_to_meters(self._depth_image, self._depth_encoding, self._depth_scale)
        source_frame = msg.header.frame_id or self._camera_info.header.frame_id or self._camera_frame_fallback
        transform = self._lookup_transform(source_frame)
        output_frame = self._target_frame if transform is not None else source_frame

        if self._detector_backend == "yolo":
            result = self._model(color, conf=self._conf, iou=self._iou, verbose=False)[0]
            detections = self._extract_yolo_detections(result, depth_m, self._camera_info, transform)
        else:
            detections = self._extract_hsv_detections(color, depth_m, self._camera_info, transform)
        self._last_raw_detection_count = len(detections)
        detections = self._apply_layout_matching(detections, output_frame)

        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = output_frame

        detection_msg = Detection3DArray()
        detection_msg.header = header
        pose_msg = PoseArray()
        pose_msg.header = header

        debug = color.copy()
        for detection in detections:
            det_msg = self._to_detection_msg(header, detection)
            detection_msg.detections.append(det_msg)
            pose_msg.poses.append(make_pose(detection.entry_position, detection.orientation_xyzw))
            self._draw_detection(debug, detection, self._camera_info)
        debug = self._compose_debug_view(debug, depth_m, detections, output_frame)

        self._detections_pub.publish(detection_msg)
        self._grasp_pose_pub.publish(pose_msg)

        if self._publish_debug_image:
            self._debug_image_pub.publish(self._bridge.cv2_to_imgmsg(debug, encoding="bgr8"))
        if self._show_debug_view:
            self._show_debug_window(debug)

    def _load_layout_objects(self, layout_path: Path) -> list[LayoutObject]:
        if not layout_path.exists():
            self.get_logger().warn(f"layout matching disabled; layout file not found: {layout_path}")
            return []

        try:
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.get_logger().warn(f"layout matching disabled; failed to read {layout_path}: {exc}")
            return []

        objects = []
        for model in layout.get("models", []):
            if model.get("collection") != "Object":
                continue
            name = str(model.get("name", "")).strip()
            class_name = layout_class_from_model_name(name)
            xyz = model.get("xyz")
            if not name or class_name is None or not isinstance(xyz, list) or len(xyz) != 3:
                continue
            objects.append(
                LayoutObject(
                    name=name,
                    class_name=class_name,
                    position=np.array([float(xyz[0]), float(xyz[1]), float(xyz[2])], dtype=float),
                )
            )
        return objects

    def _apply_layout_matching(
        self,
        detections: list[DetectionPose],
        output_frame: str,
    ) -> list[DetectionPose]:
        if not self._enable_layout_matching:
            return detections
        if not self._layout_objects:
            return detections
        if self._target_frame and output_frame != self._target_frame:
            self.get_logger().warn(
                "Skipping layout matching because detections are not in the layout frame",
                throttle_duration_sec=2.0,
            )
            return detections

        max_distance = max(0.0, self._layout_match_max_distance)
        used_detection_indices: set[int] = set()
        matched = []

        for layout_object in self._layout_objects:
            best_index = None
            best_distance = math.inf
            best_detection = None

            for index, detection in enumerate(detections):
                if index in used_detection_indices:
                    continue
                if not class_matches_layout(detection.class_name, layout_object.class_name):
                    continue
                distance = float(np.linalg.norm(detection.centroid_target - layout_object.position))
                if max_distance > 0.0 and distance > max_distance:
                    continue
                if distance < best_distance:
                    best_index = index
                    best_distance = distance
                    best_detection = detection

            if best_detection is None or best_index is None:
                continue

            used_detection_indices.add(best_index)
            matched.append(self._make_layout_matched_detection(best_detection, layout_object, best_distance))

        if self._layout_match_publish_unmatched:
            for index, detection in enumerate(detections):
                if index not in used_detection_indices:
                    matched.append(detection)
        return matched

    def _make_layout_matched_detection(
        self,
        detection: DetectionPose,
        layout_object: LayoutObject,
        distance: float,
    ) -> DetectionPose:
        layout_weight = self._layout_pose_weight
        matched_center = (1.0 - layout_weight) * detection.centroid_target + layout_weight * layout_object.position
        entry_offset = detection.entry_position - detection.centroid_target
        score = float(detection.score)
        if self._layout_match_max_distance > 1e-6:
            score *= 1.0 - 0.20 * min(distance / self._layout_match_max_distance, 1.0)

        return DetectionPose(
            class_name=layout_object.class_name,
            score=score,
            bbox_xyxy=detection.bbox_xyxy,
            centroid_source=detection.centroid_source,
            axes_source=detection.axes_source,
            extents=detection.extents,
            centroid_target=matched_center,
            axes_target=detection.axes_target,
            orientation_xyzw=detection.orientation_xyzw,
            entry_position=matched_center + entry_offset,
            layout_name=layout_object.name,
            layout_distance_m=distance,
        )

    def _extract_yolo_detections(
        self,
        result,
        depth_m: np.ndarray,
        camera_info: CameraInfo,
        transform: TransformStamped | None,
    ) -> list[DetectionPose]:
        if result.boxes is None or len(result.boxes) == 0:
            return []

        names = result.names
        boxes = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        class_ids = result.boxes.cls.cpu().numpy().astype(int)
        detections = []

        for bbox, score, class_id in zip(boxes, scores, class_ids):
            class_name = str(names[class_id])
            if self._class_allowlist and class_name not in self._class_allowlist:
                continue

            x1, y1, x2, y2 = self._clamp_bbox(bbox, depth_m.shape)
            detection = self._make_detection_from_region(
                class_name,
                float(score),
                (x1, y1, x2, y2),
                depth_m,
                camera_info,
                transform,
            )
            if detection is not None:
                detections.append(detection)
        return detections

    def _extract_hsv_detections(
        self,
        color: np.ndarray,
        depth_m: np.ndarray,
        camera_info: CameraInfo,
        transform: TransformStamped | None,
    ) -> list[DetectionPose]:
        hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
        detections = []

        for rule in HSV_RULES:
            mask = self._mask_for_hsv_rule(hsv, rule)
            if not np.any(mask):
                continue

            image_area = float(mask.shape[0] * mask.shape[1])
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < self._hsv_min_area_px:
                    continue
                if image_area > 0.0 and area > image_area * self._hsv_max_area_fraction:
                    continue

                x, y, w, h = cv2.boundingRect(contour)
                if w <= 1 or h <= 1:
                    continue
                fill_ratio = area / max(float(w * h), 1.0)
                if fill_ratio < self._hsv_min_fill_ratio:
                    continue

                bbox = (x, y, x + w, y + h)
                detection = self._make_detection_from_region(
                    rule.class_name,
                    rule.score,
                    bbox,
                    depth_m,
                    camera_info,
                    transform,
                    mask,
                )
                if detection is None:
                    continue

                if rule.class_name == "red_object" and not self._enable_layout_matching:
                    detection.class_name = self._classify_red_detection(detection)
                    if detection.class_name is None:
                        continue

                if self._class_allowlist and detection.class_name not in self._class_allowlist:
                    continue
                detections.append(detection)

        return detections

    def _mask_for_hsv_rule(self, hsv: np.ndarray, rule: HsvDetectionRule) -> np.ndarray:
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lower, upper in rule.ranges:
            mask = cv2.bitwise_or(
                mask,
                cv2.inRange(
                    hsv,
                    np.array(lower, dtype=np.uint8),
                    np.array(upper, dtype=np.uint8),
                ),
            )

        kernel_size = self._hsv_morph_kernel
        if kernel_size > 1:
            kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        return mask

    def _classify_red_detection(self, detection: DetectionPose) -> str | None:
        max_extent = float(np.max(detection.extents))
        x1, y1, x2, y2 = detection.bbox_xyxy
        bbox_aspect = float(y2 - y1) / max(float(x2 - x1), 1.0)
        if max_extent >= self._hsv_red_ketchup_min_extent_m or bbox_aspect >= 2.8:
            return "ketchup"
        return "coke"

    def _make_detection_from_region(
        self,
        class_name: str,
        score: float,
        bbox: tuple[int, int, int, int],
        depth_m: np.ndarray,
        camera_info: CameraInfo,
        transform: TransformStamped | None,
        mask: np.ndarray | None = None,
    ) -> DetectionPose | None:
        x1, y1, x2, y2 = bbox
        if mask is None:
            roi_points = self._points_from_bbox(depth_m, camera_info, x1, y1, x2, y2)
        else:
            roi_points = self._points_from_mask(depth_m, camera_info, mask, x1, y1, x2, y2)
        pca = pca_from_points(roi_points)
        if pca is None:
            return None

        centroid_target = transform_points(pca.centroid.reshape(1, 3), transform)[0]
        axes_target = transform_axes(pca.axes, transform)
        view_axis_source = normalize(
            pca.centroid,
            np.array([0.0, 0.0, 1.0], dtype=float),
        )
        view_axis_target = transform_axes(view_axis_source.reshape(3, 1), transform).reshape(3)
        quat = axes_to_quaternion(axes_target[:, 0], view_axis_target)
        entry_position = centroid_target - normalize(view_axis_target, np.array([0.0, 0.0, 1.0])) * self._entry_distance

        return DetectionPose(
            class_name=class_name,
            score=score,
            bbox_xyxy=bbox,
            centroid_source=pca.centroid,
            axes_source=pca.axes,
            extents=pca.extents,
            centroid_target=centroid_target,
            axes_target=axes_target,
            orientation_xyzw=quat,
            entry_position=entry_position,
        )

    def _clamp_bbox(self, bbox: np.ndarray, shape: tuple[int, int]) -> tuple[int, int, int, int]:
        height, width = shape
        x1 = int(max(0, min(width - 1, math.floor(float(bbox[0])))))
        y1 = int(max(0, min(height - 1, math.floor(float(bbox[1])))))
        x2 = int(max(x1 + 1, min(width, math.ceil(float(bbox[2])))))
        y2 = int(max(y1 + 1, min(height, math.ceil(float(bbox[3])))))
        return x1, y1, x2, y2

    def _points_from_bbox(
        self,
        depth_m: np.ndarray,
        camera_info: CameraInfo,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
    ) -> np.ndarray:
        roi = depth_m[y1:y2:self._roi_stride, x1:x2:self._roi_stride]
        ys, xs = np.mgrid[y1:y2:self._roi_stride, x1:x2:self._roi_stride]
        valid = np.isfinite(roi) & (roi >= self._min_depth) & (roi <= self._max_depth)
        if not np.any(valid):
            return np.empty((0, 3), dtype=float)
        return deproject(xs[valid].astype(float), ys[valid].astype(float), roi[valid].astype(float), camera_info)

    def _points_from_mask(
        self,
        depth_m: np.ndarray,
        camera_info: CameraInfo,
        mask: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
    ) -> np.ndarray:
        roi = depth_m[y1:y2:self._roi_stride, x1:x2:self._roi_stride]
        mask_roi = mask[y1:y2:self._roi_stride, x1:x2:self._roi_stride] > 0
        ys, xs = np.mgrid[y1:y2:self._roi_stride, x1:x2:self._roi_stride]
        valid = mask_roi & np.isfinite(roi) & (roi >= self._min_depth) & (roi <= self._max_depth)
        if not np.any(valid):
            return np.empty((0, 3), dtype=float)
        return deproject(xs[valid].astype(float), ys[valid].astype(float), roi[valid].astype(float), camera_info)

    def _to_detection_msg(self, header: Header, detection: DetectionPose) -> Detection3D:
        pose = make_pose(detection.centroid_target, detection.orientation_xyzw)

        det = Detection3D()
        det.header = header
        det.bbox = BoundingBox3D()
        det.bbox.center = pose
        det.bbox.size.x = float(max(detection.extents[0], 1e-4))
        det.bbox.size.y = float(max(detection.extents[1], 1e-4))
        det.bbox.size.z = float(max(detection.extents[2], 1e-4))
        det.id = detection.layout_name

        hyp = ObjectHypothesisWithPose()
        hyp.hypothesis.class_id = detection.class_name
        hyp.hypothesis.score = detection.score
        hyp.pose.pose = pose
        det.results.append(hyp)
        return det

    def _draw_detection(self, image: np.ndarray, detection: DetectionPose, camera_info: CameraInfo) -> None:
        x1, y1, x2, y2 = detection.bbox_xyxy
        cv2.rectangle(image, (x1, y1), (x2, y2), (30, 220, 30), 2)
        label_name = detection.layout_name or detection.class_name
        label = f"{label_name} {detection.score:.2f}"
        text_scale = 0.46
        text_thickness = 1
        (text_width, text_height), baseline = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            text_scale,
            text_thickness,
        )
        label_x = x1
        label_y = max(text_height + 8, y1 - 6)
        cv2.rectangle(
            image,
            (label_x - 2, label_y - text_height - 5),
            (label_x + text_width + 4, label_y + baseline + 2),
            (18, 24, 20),
            -1,
        )
        cv2.putText(
            image,
            label,
            (label_x, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            text_scale,
            (80, 255, 110),
            text_thickness,
            cv2.LINE_AA,
        )

        center = detection.centroid_source
        axis = detection.axes_source[:, 0]
        p0 = self._project(center, camera_info)
        p1 = self._project(center + axis * 0.08, camera_info)
        if p0 is not None and p1 is not None:
            cv2.circle(image, p0, 4, (0, 0, 255), -1)
            cv2.line(image, p0, p1, (0, 0, 255), 2)

        entry_source = detection.centroid_source - normalize(
            detection.centroid_source,
            np.array([0.0, 0.0, 1.0], dtype=float),
        ) * self._entry_distance
        p_entry = self._project(entry_source, camera_info)
        if p_entry is not None:
            cv2.circle(image, p_entry, 5, (255, 120, 0), -1)
            if p0 is not None:
                cv2.line(image, p_entry, p0, (255, 120, 0), 1)

    def _compose_debug_view(
        self,
        color_debug: np.ndarray,
        depth_m: np.ndarray,
        detections: list[DetectionPose],
        output_frame: str,
    ) -> np.ndarray:
        now = time.monotonic()
        dt = max(now - self._last_ui_time, 1e-6)
        self._last_ui_time = now
        instant_fps = 1.0 / dt
        self._ui_fps = instant_fps if self._ui_fps <= 0.0 else (0.85 * self._ui_fps + 0.15 * instant_fps)

        height, width = color_debug.shape[:2]
        panel_width = 420
        panel = np.full((height, panel_width, 3), (28, 30, 33), dtype=np.uint8)
        view = np.hstack([color_debug, panel])

        self._draw_status_text(
            view,
            [
                "D435 Gazebo Vision",
                f"backend: {self._detector_backend}",
                f"layout match: {self._enable_layout_matching}",
                f"frame: {output_frame}",
                f"detections: {len(detections)} / raw {self._last_raw_detection_count}",
                f"fps: {self._ui_fps:.1f}",
                "q/esc: close view",
            ],
            x=width + 16,
            y=28,
            color=(230, 235, 240),
        )

        depth_preview = self._make_depth_preview(depth_m, max_width=panel_width - 32)
        y_depth = 150
        view[y_depth:y_depth + depth_preview.shape[0], width + 16:width + 16 + depth_preview.shape[1]] = depth_preview
        cv2.putText(view, "depth", (width + 16, y_depth - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (190, 210, 255), 1)

        y = y_depth + depth_preview.shape[0] + 34
        if not detections:
            cv2.putText(view, "no detections", (width + 16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (120, 130, 140), 1)
            return view

        for idx, detection in enumerate(detections[:8], start=1):
            center = detection.centroid_target
            extents = detection.extents
            object_name = detection.layout_name or detection.class_name
            match_text = (
                f"d={detection.layout_distance_m:.3f}m"
                if math.isfinite(detection.layout_distance_m) else "d=n/a"
            )
            lines = [
                f"{idx}. {object_name}  {detection.class_name}  {detection.score:.2f}  {match_text}",
                f"   xyz {center[0]:+.3f} {center[1]:+.3f} {center[2]:+.3f}"
                f"   size {extents[0]:.3f} {extents[1]:.3f} {extents[2]:.3f}",
            ]
            self._draw_status_text(view, lines, x=width + 16, y=y, color=(225, 230, 235), line_height=20)
            y += 48
            if y > height - 40:
                break
        return view

    def _draw_status_text(
        self,
        image: np.ndarray,
        lines: list[str],
        x: int,
        y: int,
        color: tuple[int, int, int],
        line_height: int = 22,
    ) -> None:
        for index, line in enumerate(lines):
            cv2.putText(
                image,
                line,
                (x, y + index * line_height),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                color,
                1,
                cv2.LINE_AA,
            )

    def _make_depth_preview(self, depth_m: np.ndarray, max_width: int) -> np.ndarray:
        valid = np.isfinite(depth_m) & (depth_m >= self._min_depth) & (depth_m <= self._max_depth)
        clipped = np.zeros_like(depth_m, dtype=np.float32)
        clipped[valid] = depth_m[valid]
        normalized = np.zeros_like(clipped, dtype=np.uint8)
        if np.any(valid):
            normalized[valid] = np.clip(
                (1.0 - (clipped[valid] - self._min_depth) / max(self._max_depth - self._min_depth, 1e-6)) * 255.0,
                0,
                255,
            ).astype(np.uint8)
        preview = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
        scale = min(max_width / max(preview.shape[1], 1), 1.0)
        target_size = (max(1, int(preview.shape[1] * scale)), max(1, int(preview.shape[0] * scale)))
        return cv2.resize(preview, target_size, interpolation=cv2.INTER_AREA)

    def _show_debug_window(self, image: np.ndarray) -> None:
        try:
            if not self._debug_window_created:
                cv2.namedWindow(self._debug_window_name, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(self._debug_window_name, 1120, 720)
                self._debug_window_created = True
            cv2.imshow(self._debug_window_name, image)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                self._show_debug_view = False
                cv2.destroyWindow(self._debug_window_name)
                self._debug_window_created = False
        except cv2.error as exc:
            self.get_logger().warn(f"Disabling OpenCV debug view: {exc}")
            self._show_debug_view = False
            self._debug_window_created = False

    def _project(self, point: np.ndarray, camera_info: CameraInfo) -> tuple[int, int] | None:
        if point[2] <= 1e-6:
            return None
        fx = camera_info.k[0]
        fy = camera_info.k[4]
        cx = camera_info.k[2]
        cy = camera_info.k[5]
        u = int(round((point[0] * fx / point[2]) + cx))
        v = int(round((point[1] * fy / point[2]) + cy))
        return u, v


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GazeboYoloPoseNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node._show_debug_view:
            cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
