#!/usr/bin/env python3
"""
person_tracking_node — YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose

구독: /robot_cam/image_raw           (sensor_msgs/Image)
      /robot_cam/image_raw/compressed (sensor_msgs/CompressedImage)
      /person_tracking/approach_target (std_msgs/Int32, group_id)
발행: /person_tracking/tracks  (dobi_npc_msgs/PersonTrackArray)
     /person_tracking/image    (sensor_msgs/Image, publish_visualization=True 시)
     /customer_pose            (geometry_msgs/PoseStamped, 접근 대상 위치)
"""
from __future__ import annotations

import os
import colorsys
import threading

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from ament_index_python.packages import get_package_share_directory

from cv_bridge import CvBridge
from sensor_msgs.msg import Image, CompressedImage
from std_msgs.msg import Header, Int32
from geometry_msgs.msg import PoseStamped

from dobi_npc_msgs.msg import PersonTrack, PersonTrackArray

os.environ.setdefault('QT_X11_NO_MITSHM', '1')


# ── 색상 팔레트 ────────────────────────────────────────────────────
_N_COLORS = 20
_PALETTE: list[tuple[int, int, int]] = []
for _i in range(_N_COLORS):
    _h = _i / _N_COLORS
    _r, _g, _b = colorsys.hsv_to_rgb(_h, 0.85, 0.95)
    _PALETTE.append((int(_b * 255), int(_g * 255), int(_r * 255)))
_SOLO_COLOR = (160, 160, 160)
_TEXT_COLOR = (255, 255, 255)


def _group_color(label: int) -> tuple[int, int, int]:
    return _SOLO_COLOR if label == -1 else _PALETTE[label % _N_COLORS]


class PersonTrackingNode(Node):
    def __init__(self):
        super().__init__('person_tracking_node')

        self.declare_parameter('input_topic', '/robot_cam/image_raw')
        self.declare_parameter('use_compressed', True)
        self.declare_parameter('yolo_model_path', '')
        self.declare_parameter('pose_model_path', '')
        self.declare_parameter('yolo_conf', 0.50)
        self.declare_parameter('yolo_iou', 0.45)
        self.declare_parameter('dbscan_eps', 450.0)
        self.declare_parameter('dbscan_min_samples', 1)
        self.declare_parameter('publish_visualization', False)

        # InvalidHandle 레이스컨디션 방지 — destroy_node 후 콜백 진입 차단
        self._alive = True
        self._lock = threading.Lock()
        self._approach_target_group = -1

        # 타이머 콜백 executor 독점 방지 — 이미지(무거운) / 제어(가벼운) 분리
        self._cb_group_img  = MutuallyExclusiveCallbackGroup()
        self._cb_group_ctrl = MutuallyExclusiveCallbackGroup()

        in_topic = self.get_parameter('input_topic').value
        use_compressed = self.get_parameter('use_compressed').value
        yolo_path = self.get_parameter('yolo_model_path').value or self._model_path('yolov8n.pt')
        pose_path = self.get_parameter('pose_model_path').value or self._model_path('pose_landmarker_lite.task')
        self._yolo_conf = float(self.get_parameter('yolo_conf').value)
        self._yolo_iou = float(self.get_parameter('yolo_iou').value)
        dbscan_eps = float(self.get_parameter('dbscan_eps').value)
        dbscan_min = int(self.get_parameter('dbscan_min_samples').value)
        self._pub_viz = bool(self.get_parameter('publish_visualization').value)

        # 모델 로드
        self.get_logger().info(f'YOLOv8 로딩: {yolo_path}')
        from ultralytics import YOLO
        self._yolo = YOLO(yolo_path)

        self.get_logger().info('BoT-SORT 초기화')
        from boxmot.trackers.botsort.botsort import BotSort
        self._tracker = BotSort(
            reid_model=None,
            track_high_thresh=0.5,
            track_low_thresh=0.1,
            new_track_thresh=0.6,
            track_buffer=30,
            match_thresh=0.8,
            proximity_thresh=0.5,
            appearance_thresh=0.25,
            frame_rate=30,
            with_reid=False,
        )

        self.get_logger().info(f'MediaPipe Pose 로딩: {pose_path}')
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        from mediapipe.tasks.python.vision.pose_landmarker import (
            PoseLandmarker, PoseLandmarkerOptions, PoseLandmarksConnections,
        )
        self._mp = mp
        self._PoseLandmarker = PoseLandmarker
        self._pose_connections = PoseLandmarksConnections.POSE_LANDMARKS
        pose_opts = PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=pose_path),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.4,
            min_pose_presence_confidence=0.4,
            min_tracking_confidence=0.4,
        )
        self._pose_tool = PoseLandmarker.create_from_options(pose_opts)

        from sklearn.cluster import DBSCAN
        self._dbscan = DBSCAN(eps=dbscan_eps, min_samples=dbscan_min)

        self._bridge = CvBridge()

        # 구독 — 이미지(무거운 콜백): cb_group_img
        if use_compressed:
            self._sub = self.create_subscription(
                CompressedImage,
                in_topic + '/compressed',
                self._cb_compressed,
                10,
                callback_group=self._cb_group_img,
            )
        else:
            self._sub = self.create_subscription(
                Image,
                in_topic,
                self._cb_image,
                10,
                callback_group=self._cb_group_img,
            )

        # 구독 — 접근 대상 그룹(가벼운 콜백): cb_group_ctrl
        self._sub_target = self.create_subscription(
            Int32,
            '/person_tracking/approach_target',
            self._cb_approach_target,
            10,
            callback_group=self._cb_group_ctrl,
        )

        # 발행
        self._pub_tracks = self.create_publisher(PersonTrackArray, '/person_tracking/tracks', 10)
        self._pub_customer_pose = self.create_publisher(PoseStamped, '/customer_pose', 10)
        if self._pub_viz:
            self._pub_img = self.create_publisher(Image, '/person_tracking/image', 10)

        self.get_logger().info('person_tracking_node 준비 완료')

    # ── 모델 경로 헬퍼 ──────────────────────────────────────────────
    def _model_path(self, filename: str) -> str:
        share = get_package_share_directory('person_tracking_pkg')
        return os.path.join(share, 'models', filename)

    # ── 콜백 ────────────────────────────────────────────────────────
    def _cb_compressed(self, msg: CompressedImage) -> None:
        if not self._alive:  # InvalidHandle 방지
            return
        arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            self._process(frame, msg.header)

    def _cb_image(self, msg: Image) -> None:
        if not self._alive:  # InvalidHandle 방지
            return
        frame = self._bridge.imgmsg_to_cv2(msg, 'bgr8')
        self._process(frame, msg.header)

    def _cb_approach_target(self, msg: Int32) -> None:
        with self._lock:
            self._approach_target_group = msg.data

    # ── 메인 파이프라인 ──────────────────────────────────────────────
    def _process(self, frame: np.ndarray, header: Header) -> None:
        # STEP 1: YOLOv8 감지
        results = self._yolo(frame, classes=[0], conf=self._yolo_conf,
                             iou=self._yolo_iou, verbose=False)
        boxes = results[0].boxes
        if boxes is not None and len(boxes):
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy().reshape(-1, 1)
            clss = boxes.cls.cpu().numpy().reshape(-1, 1)
            dets = np.hstack([xyxy, confs, clss])
        else:
            dets = np.empty((0, 6), dtype=np.float32)

        # STEP 2: DBSCAN 그룹 클러스터링
        group_labels = np.array([], dtype=int)
        if len(dets):
            centers = (dets[:, :2] + dets[:, 2:4]) / 2
            group_labels = self._dbscan.fit_predict(centers)

        # STEP 3: BoT-SORT 추적
        tracks = self._tracker.update(dets, frame.copy())

        # STEP 4: MediaPipe Pose (시각화 시에만)
        if self._pub_viz and len(tracks):
            for track in tracks:
                tx1, ty1, tx2, ty2 = (int(track[0]), int(track[1]),
                                      int(track[2]), int(track[3]))
                det_idx = int(track[7]) if track.shape[0] > 7 else -1
                glabel = (int(group_labels[det_idx])
                          if 0 <= det_idx < len(group_labels) else -1)
                self._draw_skeleton(frame, tx1, ty1, tx2, ty2, _group_color(glabel))

        # 메시지 발행
        self._publish_tracks(tracks, dets, group_labels, header)
        self._publish_customer_pose(tracks, group_labels, header, frame.shape)

        if self._pub_viz:
            self._draw_boxes(frame, tracks, dets, group_labels)
            img_msg = self._bridge.cv2_to_imgmsg(frame, 'bgr8')
            img_msg.header = header
            self._pub_img.publish(img_msg)

    def _publish_customer_pose(self, tracks, group_labels, header, frame_shape) -> None:
        """BoT-SORT 추적 결과 → /customer_pose (PoseStamped) 발행.

        접근 대상 그룹에서 bbox 면적이 가장 큰 사람(가장 가까운 사람)을 대표로 선정.
        x = bbox 중심 x / 이미지 너비  (0~1, 좌→우)
        y = bbox 중심 y / 이미지 높이  (0~1, 상→하)
        frame_id = robot_cam_link
        """
        if not self._alive:
            return
        with self._lock:
            target_gid = self._approach_target_group
        self.get_logger().debug(
            f'customer_pose: target_gid={target_gid} tracks={len(tracks)} group_labels={list(group_labels)}'
        )
        if target_gid < 0 or len(tracks) == 0:
            return

        H, W = frame_shape[:2]
        best_track = None
        best_area = 0.0
        for track in tracks:
            det_idx = int(track[7]) if track.shape[0] > 7 else -1
            glabel = int(group_labels[det_idx]) if 0 <= det_idx < len(group_labels) else -1
            self.get_logger().debug(f'  track det_idx={det_idx} glabel={glabel} target={target_gid}')
            if glabel != target_gid:
                continue
            area = float((track[2] - track[0]) * (track[3] - track[1]))
            if area > best_area:
                best_area = area
                best_track = track

        if best_track is None:
            return

        cx = (float(best_track[0]) + float(best_track[2])) / 2.0
        cy = (float(best_track[1]) + float(best_track[3])) / 2.0
        bh = (float(best_track[3]) - float(best_track[1])) / H  # bbox 높이 비율 (0~1, 클수록 가까움)

        pose = PoseStamped()
        pose.header = header
        pose.header.frame_id = 'robot_cam_link'
        pose.pose.position.x = cx / W   # 0~1 정규화 (좌우)
        pose.pose.position.y = cy / H   # 0~1 정규화 (상하)
        pose.pose.position.z = bh       # bbox 높이 비율 (거리 프록시)
        pose.pose.orientation.w = 1.0
        self._pub_customer_pose.publish(pose)

    def _publish_tracks(self, tracks, dets, group_labels, header):
        arr = PersonTrackArray()
        arr.header = header

        n_groups = int(np.max(group_labels) + 1) if len(group_labels) > 0 else 0
        arr.group_count = n_groups

        for track in tracks:
            x1, y1, x2, y2 = float(track[0]), float(track[1]), float(track[2]), float(track[3])
            tid = int(track[4])
            conf = float(track[5])
            det_idx = int(track[7]) if track.shape[0] > 7 else -1

            if 0 <= det_idx < len(group_labels):
                glabel = int(group_labels[det_idx])
            else:
                glabel = -1

            pt = PersonTrack()
            pt.header = header
            pt.track_id = tid
            pt.group_id = glabel
            pt.bbox = [x1, y1, x2, y2]
            pt.confidence = conf
            arr.tracks.append(pt)

        self._pub_tracks.publish(arr)

    def _draw_skeleton(self, frame, x1, y1, x2, y2, color):
        H, W = frame.shape[:2]
        pad = 15
        cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
        cx2, cy2 = min(W, x2 + pad), min(H, y2 + pad)
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.shape[0] < 32 or crop.shape[1] < 32:
            return
        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        mp_img = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(crop_rgb),
        )
        result = self._pose_tool.detect(mp_img)
        if not result.pose_landmarks:
            return
        ch, cw = crop.shape[:2]
        lms = result.pose_landmarks[0]
        for conn in self._pose_connections:
            s, e = lms[conn.start], lms[conn.end]
            if s.visibility < 0.5 or e.visibility < 0.5:
                continue
            sx, sy = int(s.x * cw) + cx1, int(s.y * ch) + cy1
            ex, ey = int(e.x * cw) + cx1, int(e.y * ch) + cy1
            cv2.line(frame, (sx, sy), (ex, ey), color, 2, cv2.LINE_AA)
        for lm in lms:
            if lm.visibility < 0.5:
                continue
            px, py = int(lm.x * cw) + cx1, int(lm.y * ch) + cy1
            cv2.circle(frame, (px, py), 4, _TEXT_COLOR, -1, cv2.LINE_AA)
            cv2.circle(frame, (px, py), 4, color, 1, cv2.LINE_AA)

    def _draw_boxes(self, frame, tracks, dets, group_labels):
        n_groups = int(np.max(group_labels) + 1) if len(group_labels) > 0 else 0
        for track in tracks:
            x1, y1, x2, y2 = int(track[0]), int(track[1]), int(track[2]), int(track[3])
            tid = int(track[4])
            conf = float(track[5])
            det_idx = int(track[7]) if track.shape[0] > 7 else -1
            glabel = int(group_labels[det_idx]) if 0 <= det_idx < len(group_labels) else -1
            color = _group_color(glabel)
            tag = f'G{glabel}' if glabel >= 0 else 'Solo'
            label = f'ID:{tid}  {tag}  {conf:.2f}'
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
            cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 6, y1), color, -1)
            cv2.putText(frame, label, (x1 + 3, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, _TEXT_COLOR, 1, cv2.LINE_AA)
        h = frame.shape[0]
        cv2.putText(frame, f'Persons : {len(tracks)}', (10, h - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 230, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, f'Groups  : {n_groups}', (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 230, 0), 2, cv2.LINE_AA)

    def destroy_node(self):
        self._alive = False  # InvalidHandle 방지 — 콜백 진입 차단
        self._pose_tool.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PersonTrackingNode()
    # MultiThreadedExecutor — 이미지 콜백(무거운)과 제어 콜백(가벼운)을 별도 스레드에서 실행.
    # SingleThreadedExecutor 사용 시 YOLO 추론이 approach_target 콜백을 블록하는 문제 방지.
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
