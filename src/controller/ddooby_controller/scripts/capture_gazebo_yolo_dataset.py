#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


CLASSES = ["bread", "sausage", "ketchup", "case", "coke", "coffee"]


@dataclass
class LabeledInstance:
    label: str
    bbox: tuple[int, int, int, int]
    contour: np.ndarray


HSV_RULES = (
    ("sausage", (((5, 90, 70), (24, 255, 255)),), 500),
    ("bread", (((20, 55, 80), (45, 255, 255)),), 600),
    ("coffee", (((5, 45, 20), (28, 255, 145)),), 500),
    ("case", (((0, 0, 155), (180, 48, 255)),), 700),
    ("red_object", (((0, 70, 45), (9, 255, 255)), ((170, 70, 45), (180, 255, 255))), 500),
)


def mask_for_rule(hsv: np.ndarray, ranges: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in ranges:
        mask = cv2.bitwise_or(
            mask,
            cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8)),
        )
    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def classify_red_bbox(x: int, y: int, w: int, h: int, image_width: int, image_height: int) -> str:
    aspect = h / max(float(w), 1.0)
    area = w * h
    center_x = x + w * 0.5
    center_y = y + h * 0.5
    if center_x < image_width * 0.34 and (aspect >= 1.6 or center_y < image_height * 0.50):
        return "ketchup"
    if aspect >= 2.4 or area >= 8000:
        return "ketchup"
    return "coke"


def plausible_box(
    label: str,
    box: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
    area: float,
    fill_ratio: float,
) -> bool:
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1
    cx = x1 + w * 0.5
    cy = y1 + h * 0.5
    aspect = h / max(float(w), 1.0)

    if label == "sausage":
        return (
            cy > image_height * 0.48
            and cx < image_width * 0.42
            and h > image_height * 0.12
            and area > 800
            and aspect > 1.15
        )
    if label == "bread":
        return (
            cy > image_height * 0.48
            and image_width * 0.22 < cx < image_width * 0.62
            and h > image_height * 0.10
            and w > image_width * 0.035
            and area > 900
        )
    if label == "coffee":
        return (
            cy < image_height * 0.72
            and image_width * 0.20 < cx < image_width * 0.75
            and aspect > 1.15
            and area > 650
            and fill_ratio > 0.18
        )
    if label == "case":
        return (
            cx > image_width * 0.52
            and cy > image_height * 0.34
            and h > image_height * 0.10
            and w > image_width * 0.045
            and area > 900
        )
    if label == "ketchup":
        return (
            cx < image_width * 0.36
            and h > image_height * 0.18
            and area > 1500
        )
    if label == "coke":
        return (
            image_width * 0.08 < cx < image_width * 0.55
            and cy < image_height * 0.78
            and h > image_height * 0.10
            and area > 900
        )
    return True


def detect_instances(frame: np.ndarray) -> list[LabeledInstance]:
    hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
    height, width = frame.shape[:2]
    image_area = float(height * width)
    instances: list[LabeledInstance] = []

    for class_name, ranges, min_area in HSV_RULES:
        mask = mask_for_rule(hsv, ranges)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > image_area * 0.22:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 8 or h < 8:
                continue
            fill_ratio = area / max(float(w * h), 1.0)
            if fill_ratio < 0.12:
                continue

            label = class_name
            if class_name == "red_object":
                label = classify_red_bbox(x, y, w, h, width, height)
            if label not in CLASSES:
                continue
            box = (x, y, x + w, y + h)
            if not plausible_box(label, box, width, height, area, fill_ratio):
                continue
            instances.append(LabeledInstance(label=label, bbox=box, contour=contour))
    return non_max_suppression(instances)


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return 0.0 if union <= 0 else inter / union


def non_max_suppression(instances: list[LabeledInstance]) -> list[LabeledInstance]:
    kept: list[LabeledInstance] = []
    for instance in sorted(
        instances,
        key=lambda item: (
            item.label,
            -((item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])),
        ),
    ):
        if any(instance.label == kept_item.label and iou(instance.bbox, kept_item.bbox) > 0.45 for kept_item in kept):
            continue
        kept.append(instance)
    return kept


def contour_to_yolo_polygon(contour: np.ndarray, width: int, height: int) -> list[float]:
    perimeter = cv2.arcLength(contour, closed=True)
    epsilon = max(1.0, perimeter * 0.01)
    approx = cv2.approxPolyDP(contour, epsilon, closed=True).reshape(-1, 2)
    if approx.shape[0] < 3:
        x, y, w, h = cv2.boundingRect(contour)
        approx = np.array(
            [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            dtype=np.float32,
        )

    polygon: list[float] = []
    for x, y in approx.astype(np.float32):
        polygon.extend(
            [
                float(np.clip(x / max(float(width), 1.0), 0.0, 1.0)),
                float(np.clip(y / max(float(height), 1.0), 0.0, 1.0)),
            ]
        )
    return polygon


def write_yolo_label(
    path: Path,
    instances: list[LabeledInstance],
    width: int,
    height: int,
    label_format: str,
) -> None:
    lines = []
    for instance in instances:
        class_id = CLASSES.index(instance.label)
        if label_format == "segment":
            polygon = contour_to_yolo_polygon(instance.contour, width, height)
            values = " ".join(f"{value:.6f}" for value in polygon)
            lines.append(f"{class_id} {values}")
            continue

        x1, y1, x2, y2 = instance.bbox
        cx = ((x1 + x2) * 0.5) / width
        cy = ((y1 + y2) * 0.5) / height
        bw = (x2 - x1) / width
        bh = (y2 - y1) / height
        lines.append(f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def draw_boxes(frame: np.ndarray, instances: list[LabeledInstance]) -> np.ndarray:
    annotated = frame.copy()
    overlay = annotated.copy()
    for instance in instances:
        label = instance.label
        x1, y1, x2, y2 = instance.bbox
        cv2.drawContours(overlay, [instance.contour], -1, (0, 180, 255), -1)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 80), 2)
        cv2.putText(annotated, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 80), 2)
    return cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0.0)


class DatasetCapture(Node):
    def __init__(self, args: argparse.Namespace):
        super().__init__("gazebo_yolo_dataset_capture")
        self.args = args
        self.bridge = CvBridge()
        self.last_capture = 0.0
        self.count = 0
        self.images_dir = Path(args.output_dir) / "images"
        self.labels_dir = Path(args.output_dir) / "labels"
        self.preview_dir = Path(args.output_dir) / "preview"
        for split in ("train", "val"):
            (self.images_dir / split).mkdir(parents=True, exist_ok=True)
            (self.labels_dir / split).mkdir(parents=True, exist_ok=True)
        if args.save_preview:
            self.preview_dir.mkdir(parents=True, exist_ok=True)

        self.create_subscription(Image, args.image_topic, self.on_image, qos_profile_sensor_data)
        self.get_logger().info(
            f"Capturing {args.count} YOLO images from {args.image_topic} into {args.output_dir}"
        )

    def on_image(self, msg: Image) -> None:
        now = time.monotonic()
        if now - self.last_capture < self.args.interval:
            return
        if self.count >= self.args.count:
            return

        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        instances = detect_instances(frame)
        if len(instances) < self.args.min_boxes:
            self.get_logger().warn(f"Skipping frame with {len(instances)} labels")
            self.last_capture = now
            return

        split = "val" if self.count % max(1, self.args.val_every) == 0 else "train"
        stem = f"gazebo_{self.count:05d}"
        image_path = self.images_dir / split / f"{stem}.jpg"
        label_path = self.labels_dir / split / f"{stem}.txt"
        cv2.imwrite(str(image_path), frame)
        write_yolo_label(label_path, instances, frame.shape[1], frame.shape[0], self.args.label_format)
        if self.args.save_preview:
            cv2.imwrite(str(self.preview_dir / f"{stem}.jpg"), draw_boxes(frame, instances))

        self.count += 1
        self.last_capture = now
        if self.count % 10 == 0 or self.count == self.args.count:
            self.get_logger().info(f"Captured {self.count}/{self.args.count}")
        if self.count >= self.args.count:
            self.write_data_yaml()
            self.get_logger().info("Dataset capture complete")
            rclpy.shutdown()

    def write_data_yaml(self) -> None:
        data_yaml = Path(self.args.output_dir) / "data.yaml"
        names = "\n".join(f"  {idx}: {name}" for idx, name in enumerate(CLASSES))
        data_yaml.write_text(
            f"path: {Path(self.args.output_dir).resolve()}\n"
            "train: images/train\n"
            "val: images/val\n"
            f"names:\n{names}\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Gazebo camera images with YOLO labels")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--image-topic", default="/realsense_d435/image")
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--interval", type=float, default=0.15)
    parser.add_argument("--val-every", type=int, default=5)
    parser.add_argument("--min-boxes", type=int, default=4)
    parser.add_argument("--label-format", choices=["segment", "detect"], default="segment")
    parser.add_argument("--save-preview", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rclpy.init()
    node = DatasetCapture(args)
    rclpy.spin(node)


if __name__ == "__main__":
    main()
