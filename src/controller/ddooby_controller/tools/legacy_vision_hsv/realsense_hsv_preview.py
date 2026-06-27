#!/usr/bin/env python3

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image


@dataclass(frozen=True)
class HsvRule:
    class_name: str
    ranges: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]
    score: float
    min_area_px: int = 450
    min_fill_ratio: float = 0.16
    max_area_fraction: float = 0.24


@dataclass
class Candidate:
    class_name: str
    score: float
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    axis: tuple[float, float]
    area: float
    aspect: float


HSV_PROFILES = {
    "gazebo": (
        HsvRule("sausage", (((5, 90, 70), (24, 255, 255)),), 0.90, 250, 0.16, 0.18),
        HsvRule("bread", (((20, 45, 70), (45, 255, 255)),), 0.82, 250, 0.16, 0.18),
        HsvRule("coffee", (((5, 45, 20), (28, 255, 145)),), 0.88, 300, 0.15, 0.12),
        HsvRule("case", (((0, 0, 145), (180, 55, 255)),), 0.78, 650, 0.14, 0.16),
        HsvRule("red_object", (((0, 70, 45), (10, 255, 255)), ((168, 70, 45), (180, 255, 255))), 0.86, 300, 0.14, 0.18),
    ),
    "realsense": (
        HsvRule("sausage", (((5, 70, 55), (21, 255, 255)),), 0.84, 700, 0.16, 0.10),
        HsvRule("bread", (((20, 80, 90), (42, 255, 255)),), 0.82, 700, 0.14, 0.10),
        HsvRule("coffee", (((5, 70, 20), (28, 255, 145)),), 0.76, 900, 0.16, 0.08),
        HsvRule("case", (((0, 0, 120), (180, 70, 255)),), 0.74, 1300, 0.12, 0.10),
        HsvRule("red_object", (((0, 70, 45), (12, 255, 255)), ((168, 70, 45), (180, 255, 255))), 0.84, 360, 0.06, 0.10),
    ),
}

MAX_DETECTIONS_BY_PROFILE = {
    "gazebo": {
        "ketchup": 1,
        "coke": 2,
        "coffee": 2,
        "sausage": 2,
        "bread": 2,
        "case": 2,
    },
    "realsense": {
        "ketchup": 1,
        "coke": 2,
        "coffee": 2,
        "sausage": 2,
        "bread": 2,
        "case": 2,
    },
}

CLASS_COLORS = {
    "ketchup": (40, 40, 245),
    "coke": (40, 40, 245),
    "coffee": (70, 120, 210),
    "sausage": (0, 150, 255),
    "bread": (0, 230, 255),
    "case": (230, 230, 230),
}


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def resolve_device(device: str):
    value = str(device).strip()
    if value and value.lower() != "auto":
        return int(value) if value.isdigit() else value

    by_id = Path("/dev/v4l/by-id")
    if by_id.exists():
        matches = sorted(by_id.glob("*RealSense*video-index0"))
        if matches:
            return str(matches[0])

    if Path("/dev/video6").exists():
        return "/dev/video6"
    return 0


def bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = float(iw * ih)
    area_a = float(max(0, ax2 - ax1) * max(0, ay2 - ay1))
    area_b = float(max(0, bx2 - bx1) * max(0, by2 - by1))
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def bbox_intersection_over_area(
    inner: tuple[int, int, int, int],
    outer: tuple[int, int, int, int],
) -> float:
    ix1 = max(inner[0], outer[0])
    iy1 = max(inner[1], outer[1])
    ix2 = min(inner[2], outer[2])
    iy2 = min(inner[3], outer[3])
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inner_area = float(max(0, inner[2] - inner[0]) * max(0, inner[3] - inner[1]))
    if inner_area <= 0.0:
        return 0.0
    return float(iw * ih) / inner_area


def bbox_contains_center(
    outer: tuple[int, int, int, int],
    inner: tuple[int, int, int, int],
) -> bool:
    cx = (inner[0] + inner[2]) * 0.5
    cy = (inner[1] + inner[3]) * 0.5
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def clamp_axis_from_vertical(axis: tuple[float, float], max_degrees: float) -> tuple[float, float]:
    ax, ay = axis
    norm = float(np.hypot(ax, ay))
    if norm < 1e-6:
        return (0.0, 1.0)

    ax /= norm
    ay /= norm
    if ay < 0.0:
        ax = -ax
        ay = -ay

    max_angle = np.deg2rad(max_degrees)
    angle = float(np.arctan2(ax, ay))
    angle = float(np.clip(angle, -max_angle, max_angle))
    return (float(np.sin(angle)), float(np.cos(angle)))


class RealSenseHsvPreview(Node):
    def __init__(self, defaults):
        super().__init__("realsense_hsv_preview")

        self.declare_parameter("device", defaults.device)
        self.declare_parameter("profile", defaults.profile)
        self.declare_parameter("width", defaults.width)
        self.declare_parameter("height", defaults.height)
        self.declare_parameter("fps", defaults.fps)
        self.declare_parameter("show_debug_view", defaults.show_debug_view)
        self.declare_parameter("publish_debug_image", True)
        self.declare_parameter("debug_image_topic", "/manufacturing_vision/debug_image")
        self.declare_parameter("debug_window_name", "manufacturing_vision")
        self.declare_parameter("process_every_n", 1)
        self.declare_parameter("morph_kernel", 5)
        self.declare_parameter("max_window_width", 1280)

        self._device_param = str(self.get_parameter("device").value)
        self._device = resolve_device(self._device_param)
        self._profile = str(self.get_parameter("profile").value).strip().lower()
        if self._profile not in HSV_PROFILES:
            self.get_logger().warn(f"Unknown profile '{self._profile}', using realsense")
            self._profile = "realsense"

        self._width = int(self.get_parameter("width").value)
        self._height = int(self.get_parameter("height").value)
        self._fps = int(self.get_parameter("fps").value)
        self._show_debug_view = as_bool(self.get_parameter("show_debug_view").value)
        self._publish_debug_image = as_bool(self.get_parameter("publish_debug_image").value)
        self._debug_window_name = str(self.get_parameter("debug_window_name").value)
        self._process_every_n = max(1, int(self.get_parameter("process_every_n").value))
        self._morph_kernel = max(1, int(self.get_parameter("morph_kernel").value))
        self._max_window_width = max(320, int(self.get_parameter("max_window_width").value))
        self._frame_count = 0
        self._last_ui_time = time.monotonic()
        self._ui_fps = 0.0
        self._window_created = False

        self._bridge = CvBridge()
        topic = str(self.get_parameter("debug_image_topic").value)
        self._debug_pub = self.create_publisher(Image, topic, 10)

    def run_camera(self) -> None:
        cap = cv2.VideoCapture(self._device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open camera device: {self._device}")

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        cap.set(cv2.CAP_PROP_FPS, self._fps)

        self.get_logger().info(
            f"RealSense HSV preview ready: device={self._device}, "
            f"profile={self._profile}, view={self._show_debug_view}"
        )

        try:
            while rclpy.ok():
                ok, frame = cap.read()
                if not ok or frame is None:
                    self.get_logger().warn("Camera frame read failed", throttle_duration_sec=2.0)
                    rclpy.spin_once(self, timeout_sec=0.01)
                    continue

                self._frame_count += 1
                if self._frame_count % self._process_every_n != 0:
                    continue

                debug = self.process_frame(frame)
                self._publish_or_show(debug)
                rclpy.spin_once(self, timeout_sec=0.0)
        finally:
            cap.release()
            self._close_window()

    def run_image_dir(self, image_dir: str, output_dir: str | None) -> None:
        source = Path(image_dir)
        images = sorted(
            path for path in source.iterdir()
            if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
        )
        if not images:
            raise RuntimeError(f"No image files found: {source}")

        sink = Path(output_dir) if output_dir else None
        if sink is not None:
            sink.mkdir(parents=True, exist_ok=True)

        self.get_logger().info(f"Processing {len(images)} images from {source}")
        for path in images:
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                self.get_logger().warn(f"Skipping unreadable image: {path}")
                continue

            debug = self.process_frame(frame)
            if sink is not None:
                cv2.imwrite(str(sink / path.name), debug)
            if self._show_debug_view:
                self._publish_or_show(debug)
                key = cv2.waitKey(30) & 0xFF
                if key in (27, ord("q")):
                    break
            rclpy.spin_once(self, timeout_sec=0.0)
        self._close_window()

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        candidates = self._extract_candidates(frame)
        candidates = self._suppress_overlaps(candidates)

        annotated = frame.copy()
        for candidate in candidates:
            self._draw_candidate(annotated, candidate)
        return self._compose_view(annotated, candidates)

    def _extract_candidates(self, frame: np.ndarray) -> list[Candidate]:
        blurred = cv2.GaussianBlur(frame, (3, 3), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        image_area = float(frame.shape[0] * frame.shape[1])
        candidates = []

        for rule in HSV_PROFILES[self._profile]:
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

            if self._profile == "realsense" and rule.class_name == "red_object":
                contours = self._red_object_contours(mask)
            else:
                if self._morph_kernel > 1:
                    kernel = np.ones((self._morph_kernel, self._morph_kernel), dtype=np.uint8)
                    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                candidate = self._candidate_from_contour(rule, contour, image_area, frame.shape)
                if candidate is not None:
                    candidates.append(candidate)

        return candidates

    def _red_object_contours(self, mask: np.ndarray) -> list[np.ndarray]:
        height = mask.shape[0]
        split_y = int(height * 0.315)
        bands = []

        top = mask.copy()
        top[split_y:, :] = 0
        bands.append((top, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 13))))

        lower = mask.copy()
        lower[:split_y, :] = 0
        bands.append((lower, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 23))))

        contours = []
        for band_mask, close_kernel in bands:
            band_mask = cv2.morphologyEx(band_mask, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8))
            band_mask = cv2.morphologyEx(band_mask, cv2.MORPH_CLOSE, close_kernel)
            band_mask = cv2.dilate(band_mask, np.ones((3, 3), dtype=np.uint8), iterations=1)
            band_contours, _ = cv2.findContours(band_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contours.extend(band_contours)
        return contours

    def _candidate_from_contour(
        self,
        rule: HsvRule,
        contour: np.ndarray,
        image_area: float,
        shape: tuple[int, int, int],
    ) -> Candidate | None:
        area = float(cv2.contourArea(contour))
        if area < rule.min_area_px:
            return None
        if image_area > 0.0 and area > image_area * rule.max_area_fraction:
            return None

        x, y, w, h = cv2.boundingRect(contour)
        if w <= 2 or h <= 2:
            return None
        fill_ratio = area / max(float(w * h), 1.0)
        if fill_ratio < rule.min_fill_ratio:
            return None

        class_name = rule.class_name
        if class_name == "red_object":
            class_name = self._classify_red_object(x, y, w, h, area, shape)

        if not self._class_specific_filter(class_name, x, y, w, h, area, fill_ratio, shape):
            return None

        center, axis = self._pca_axis(contour, x, y, w, h)
        if self._profile == "realsense" and class_name == "ketchup":
            center = (x + w // 2, y + h // 2)
        if self._profile == "realsense" and class_name == "coke":
            axis = clamp_axis_from_vertical(axis, 24.0)
        score = self._class_specific_score(rule.score, class_name, x, y, w, h, area, shape)
        return Candidate(
            class_name=class_name,
            score=score,
            bbox=(x, y, x + w, y + h),
            center=center,
            axis=axis,
            area=area,
            aspect=float(max(w, h)) / max(float(min(w, h)), 1.0),
        )

    def _classify_red_object(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        area: float,
        shape: tuple[int, int, int],
    ) -> str:
        image_h, image_w = shape[:2]
        aspect = float(h) / max(float(w), 1.0)
        center_x = (x + w * 0.5) / max(float(image_w), 1.0)
        center_y = (y + h * 0.5) / max(float(image_h), 1.0)
        area_fraction = area / max(float(image_h * image_w), 1.0)
        top_shelf_bottle = (
            center_y <= 0.36
            and 0.08 <= center_x <= 0.55
            and w >= image_w * 0.045
            and h >= image_h * 0.12
            and area_fraction >= 0.004
        )
        if top_shelf_bottle:
            return "ketchup"
        return "coke"

    def _class_specific_filter(
        self,
        class_name: str,
        x: int,
        y: int,
        w: int,
        h: int,
        area: float,
        fill_ratio: float,
        shape: tuple[int, int, int],
    ) -> bool:
        image_h, image_w = shape[:2]
        aspect = float(max(w, h)) / max(float(min(w, h)), 1.0)
        vertical_aspect = float(h) / max(float(w), 1.0)
        cx = (x + w * 0.5) / max(float(image_w), 1.0)
        cy = (y + h * 0.5) / max(float(image_h), 1.0)
        area_fraction = area / max(float(image_h * image_w), 1.0)

        if self._profile == "realsense":
            if class_name == "sausage":
                return (
                    aspect >= 1.45
                    and area_fraction <= 0.018
                    and 0.18 <= cx <= 0.58
                    and cy >= 0.50
                )
            if class_name == "bread":
                return (
                    aspect >= 1.25
                    and area_fraction <= 0.022
                    and 0.24 <= cx <= 0.70
                    and cy >= 0.50
                )
            if class_name == "coffee":
                return (
                    vertical_aspect >= 1.15
                    and w >= image_w * 0.025
                    and h >= image_h * 0.075
                    and w <= image_w * 0.14
                    and h <= image_h * 0.36
                    and 0.16 <= cx <= 0.66
                    and 0.22 <= cy <= 0.62
                )
            if class_name == "coke":
                return (
                    vertical_aspect >= 0.85
                    and w >= image_w * 0.025
                    and h >= image_h * 0.055
                    and w <= image_w * 0.16
                    and h <= image_h * 0.42
                    and 0.14 <= cx <= 0.68
                    and 0.24 <= cy <= 0.66
                    and area_fraction <= 0.030
                )
            if class_name == "ketchup":
                return (
                    vertical_aspect >= 1.05
                    and w >= image_w * 0.035
                    and h >= image_h * 0.12
                    and w <= image_w * 0.20
                    and h <= image_h * 0.55
                    and 0.08 <= cx <= 0.55
                    and cy <= 0.45
                )
            if class_name == "case":
                return (
                    w >= image_w * 0.045
                    and h >= image_h * 0.08
                    and 0.42 <= cx <= 0.98
                    and cy >= 0.48
                    and area_fraction <= 0.060
                    and fill_ratio >= 0.12
                )

        if class_name in ("sausage", "bread"):
            return aspect >= 1.25 and h >= 18 and w >= 12
        if class_name in ("coke", "coffee", "ketchup"):
            return h >= 25 and w >= 12
        if class_name == "case":
            if w < 28 or h < 28:
                return False
            if x <= 4 or y <= 4 or x + w >= image_w - 4 or y + h >= image_h - 4:
                return False
            if fill_ratio < 0.10:
                return False
            return True
        return True

    def _class_specific_score(
        self,
        base_score: float,
        class_name: str,
        x: int,
        y: int,
        w: int,
        h: int,
        area: float,
        shape: tuple[int, int, int],
    ) -> float:
        if self._profile != "realsense":
            return base_score

        image_h, image_w = shape[:2]
        cx = (x + w * 0.5) / max(float(image_w), 1.0)
        cy = (y + h * 0.5) / max(float(image_h), 1.0)
        vertical_aspect = float(h) / max(float(w), 1.0)
        score = base_score

        if class_name == "ketchup":
            score += 0.10 * min(vertical_aspect / 2.2, 1.0)
            score += 0.08 * (1.0 - min(abs(cx - 0.26) / 0.26, 1.0))
        elif class_name in ("coke", "coffee"):
            score += 0.08 * min(vertical_aspect / 2.0, 1.0)
            score += 0.06 * (1.0 - min(abs(cx - 0.36) / 0.36, 1.0))
        elif class_name in ("sausage", "bread"):
            horizontal_aspect = float(w) / max(float(h), 1.0)
            score += 0.08 * min(max(horizontal_aspect, vertical_aspect) / 2.0, 1.0)
            score += 0.05 * (1.0 - min(abs(cy - 0.76) / 0.35, 1.0))
        elif class_name == "case":
            score += 0.06 * (1.0 - min(abs(cy - 0.72) / 0.30, 1.0))

        score += 0.02 * min(area / max(float(image_h * image_w) * 0.01, 1.0), 1.0)
        return float(score)

    def _pca_axis(
        self,
        contour: np.ndarray,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> tuple[tuple[int, int], tuple[float, float]]:
        points = contour.reshape(-1, 2).astype(np.float32)
        if len(points) >= 6:
            mean, eigenvectors = cv2.PCACompute(points, mean=None, maxComponents=2)
            center = (int(mean[0, 0]), int(mean[0, 1]))
            axis = (float(eigenvectors[0, 0]), float(eigenvectors[0, 1]))
            return center, axis
        return (x + w // 2, y + h // 2), (1.0, 0.0)

    def _suppress_overlaps(self, candidates: list[Candidate]) -> list[Candidate]:
        priority = {
            "ketchup": 6,
            "coke": 5,
            "bread": 5,
            "sausage": 5,
            "coffee": 4,
            "case": 4,
        }
        ordered = sorted(
            candidates,
            key=lambda item: (priority.get(item.class_name, 0), item.score, item.area),
            reverse=True,
        )
        kept: list[Candidate] = []
        for candidate in ordered:
            overlaps = False
            for other in kept:
                iou = bbox_iou(candidate.bbox, other.bbox)
                if candidate.class_name == "coffee" and other.class_name in ("coke", "ketchup"):
                    contained = bbox_intersection_over_area(candidate.bbox, other.bbox)
                    if contained > 0.25 or bbox_contains_center(other.bbox, candidate.bbox) or iou > 0.12:
                        overlaps = True
                        break
                if candidate.class_name == other.class_name and iou > 0.35:
                    overlaps = True
                    break
                if iou > 0.68:
                    overlaps = True
                    break
            if not overlaps:
                kept.append(candidate)
        return self._limit_class_counts(kept)

    def _limit_class_counts(self, candidates: list[Candidate]) -> list[Candidate]:
        limits = MAX_DETECTIONS_BY_PROFILE.get(self._profile, {})
        counts: Counter[str] = Counter()
        limited = []
        for candidate in candidates:
            limit = limits.get(candidate.class_name, 99)
            if counts[candidate.class_name] >= limit:
                continue
            counts[candidate.class_name] += 1
            limited.append(candidate)
        return limited[:12]

    def _draw_candidate(self, frame: np.ndarray, candidate: Candidate) -> None:
        x1, y1, x2, y2 = candidate.bbox
        color = CLASS_COLORS.get(candidate.class_name, (60, 240, 80))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        label = candidate.class_name
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.48
        thickness = 1
        (tw, th), baseline = cv2.getTextSize(label, font, scale, thickness)
        label_y = max(th + 7, y1 - 5)
        cv2.rectangle(
            frame,
            (x1 - 1, label_y - th - 6),
            (x1 + tw + 6, label_y + baseline + 2),
            (18, 22, 20),
            -1,
        )
        cv2.putText(frame, label, (x1 + 2, label_y), font, scale, color, thickness, cv2.LINE_AA)

        cx, cy = candidate.center
        ax, ay = candidate.axis
        axis_len = min(max(x2 - x1, y2 - y1) * 0.45, 80)
        p1 = (int(cx - ax * axis_len), int(cy - ay * axis_len))
        p2 = (int(cx + ax * axis_len), int(cy + ay * axis_len))
        cv2.circle(frame, (cx, cy), 4, (255, 80, 0), -1)
        cv2.line(frame, p1, p2, (0, 0, 255), 2)

    def _compose_view(self, frame: np.ndarray, candidates: list[Candidate]) -> np.ndarray:
        now = time.monotonic()
        dt = max(now - self._last_ui_time, 1e-6)
        self._last_ui_time = now
        instant_fps = 1.0 / dt
        self._ui_fps = instant_fps if self._ui_fps <= 0.0 else 0.85 * self._ui_fps + 0.15 * instant_fps

        h, w = frame.shape[:2]
        panel_w = 330
        panel = np.full((h, panel_w, 3), (28, 30, 33), dtype=np.uint8)
        view = np.hstack([frame, panel])

        lines = [
            "D435 HSV Vision",
            f"device: {self._device_param}",
            f"profile: {self._profile}",
            f"detections: {len(candidates)}",
            f"fps: {self._ui_fps:.1f}",
            "q/esc: close",
        ]
        y = 28
        for index, line in enumerate(lines):
            color = (245, 245, 245) if index == 0 else (210, 220, 225)
            scale = 0.58 if index == 0 else 0.45
            cv2.putText(view, line, (w + 16, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
            y += 25

        y += 14
        counts = Counter(candidate.class_name for candidate in candidates)
        for class_name in ("ketchup", "coke", "coffee", "sausage", "bread", "case"):
            count = counts.get(class_name, 0)
            color = CLASS_COLORS.get(class_name, (60, 240, 80))
            cv2.rectangle(view, (w + 18, y - 13), (w + 30, y - 1), color, -1)
            cv2.putText(
                view,
                f"{class_name}: {count}",
                (w + 40, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (220, 225, 230),
                1,
                cv2.LINE_AA,
            )
            y += 24

        return view

    def _publish_or_show(self, debug: np.ndarray) -> None:
        if self._publish_debug_image and rclpy.ok():
            try:
                self._debug_pub.publish(self._bridge.cv2_to_imgmsg(debug, encoding="bgr8"))
            except Exception as exc:
                if rclpy.ok():
                    self.get_logger().warn(f"Failed to publish debug image: {exc}", throttle_duration_sec=2.0)

        if not self._show_debug_view:
            return

        if not self._window_created:
            cv2.namedWindow(self._debug_window_name, cv2.WINDOW_NORMAL)
            self._window_created = True

        display = debug
        if debug.shape[1] > self._max_window_width:
            scale = self._max_window_width / float(debug.shape[1])
            display = cv2.resize(debug, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        cv2.imshow(self._debug_window_name, display)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            self._show_debug_view = False
            self._close_window()

    def _close_window(self) -> None:
        if self._window_created:
            cv2.destroyWindow(self._debug_window_name)
            self._window_created = False


def parse_args():
    parser = argparse.ArgumentParser(description="RealSense HSV manufacturing vision preview")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--profile", default="realsense", choices=sorted(HSV_PROFILES.keys()))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--image-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--show-debug-view", dest="show_debug_view", action="store_true", default=True)
    parser.add_argument("--no-window", dest="show_debug_view", action="store_false")
    args, ros_args = parser.parse_known_args()
    return args, ros_args


def main():
    args, ros_args = parse_args()
    rclpy.init(args=ros_args)
    node = RealSenseHsvPreview(args)

    try:
        if args.image_dir:
            node.run_image_dir(args.image_dir, args.output_dir or None)
        else:
            node.run_camera()
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
