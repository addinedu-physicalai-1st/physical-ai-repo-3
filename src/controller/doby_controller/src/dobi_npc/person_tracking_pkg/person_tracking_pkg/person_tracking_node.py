#!/usr/bin/env python3
"""
person_tracking_node — YOLOv8 + DBSCAN + BoT-SORT

구독: /robot_cam/image_raw           (sensor_msgs/Image)
      /robot_cam/image_raw/compressed (sensor_msgs/CompressedImage)
      /person_tracking/approach_target (std_msgs/Int32, group_id)
발행: /person_tracking/tracks  (dobi_npc_msgs/PersonTrackArray)
     /customer_pose            (geometry_msgs/PoseStamped, 접근 대상 위치)
"""
from __future__ import annotations

import os
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


class PersonTrackingNode(Node):
    def __init__(self):
        super().__init__('person_tracking_node')

        self.declare_parameter('input_topic', '/robot_cam/image_raw')
        self.declare_parameter('use_compressed', True)
        self.declare_parameter('yolo_model_path', '')
        self.declare_parameter('yolo_device', 'cpu')  # 'cpu' 또는 'cuda:0'
        self.declare_parameter('yolo_conf', 0.50)
        self.declare_parameter('yolo_iou', 0.45)
        self.declare_parameter('dbscan_eps', 450.0)
        self.declare_parameter('dbscan_min_samples', 1)
        self.declare_parameter('frame_skip', 1)  # GPU 사용 시 1 (전 프레임 처리), CPU 시 3

        # InvalidHandle 레이스컨디션 방지 — destroy_node 후 콜백 진입 차단
        self._alive = True
        self._lock = threading.Lock()
        self._approach_target_group = -1
        self._frame_skip = int(self.get_parameter('frame_skip').value)
        self._frame_count = 0

        # 타이머 콜백 executor 독점 방지 — 이미지(무거운) / 제어(가벼운) 분리
        self._cb_group_img  = MutuallyExclusiveCallbackGroup()
        self._cb_group_ctrl = MutuallyExclusiveCallbackGroup()

        in_topic = self.get_parameter('input_topic').value
        use_compressed = self.get_parameter('use_compressed').value
        yolo_path = self.get_parameter('yolo_model_path').value or self._model_path('yolov8n.pt')
        self._yolo_device = self.get_parameter('yolo_device').value
        self._yolo_conf = float(self.get_parameter('yolo_conf').value)
        self._yolo_iou = float(self.get_parameter('yolo_iou').value)
        dbscan_eps = float(self.get_parameter('dbscan_eps').value)
        dbscan_min = int(self.get_parameter('dbscan_min_samples').value)

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

        self.get_logger().info('person_tracking_node 준비 완료')

    # ── 모델 경로 헬퍼 ──────────────────────────────────────────────
    def _model_path(self, filename: str) -> str:
        share = get_package_share_directory('person_tracking_pkg')
        return os.path.join(share, 'models', filename)

    # ── 콜백 ────────────────────────────────────────────────────────
    def _cb_compressed(self, msg: CompressedImage) -> None:
        if not self._alive:  # InvalidHandle 방지
            return
        self._frame_count += 1
        if self._frame_count % self._frame_skip != 0:
            return
        arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            self._process(frame, msg.header)

    def _cb_image(self, msg: Image) -> None:
        if not self._alive:  # InvalidHandle 방지
            return
        self._frame_count += 1
        if self._frame_count % self._frame_skip != 0:
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
                             iou=self._yolo_iou, verbose=False, device=self._yolo_device)
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

        # 메시지 발행
        self._publish_tracks(tracks, dets, group_labels, header)
        self._publish_customer_pose(tracks, group_labels, header, frame.shape)

    def _publish_customer_pose(self, tracks, group_labels, header, frame_shape) -> None:
        """BoT-SORT 추적 결과 → /customer_pose (PoseStamped) 발행.

        접근 대상 그룹에서 bbox 면적이 가장 큰 사람(가장 가까운 사람)을 대표로 선정.
        x = bbox 중심 x / 이미지 너비  (0~1, 좌→우)
        y = bbox 중심 y / 이미지 높이  (0~1, 상→하)
        z = bbox 높이 비율             (0~1, 클수록 가까움)
        """
        if not self._alive:
            return
        with self._lock:
            target_gid = self._approach_target_group
        if target_gid < 0 or len(tracks) == 0:
            return

        H, W = frame_shape[:2]
        best_track = None
        best_area = 0.0
        for track in tracks:
            det_idx = int(track[7]) if track.shape[0] > 7 else -1
            glabel = int(group_labels[det_idx]) if 0 <= det_idx < len(group_labels) else -1
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
        bh = (float(best_track[3]) - float(best_track[1])) / H

        pose = PoseStamped()
        pose.header = header
        pose.header.frame_id = 'robot_cam_link'
        pose.pose.position.x = cx / W
        pose.pose.position.y = cy / H
        pose.pose.position.z = bh
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

    def destroy_node(self):
        self._alive = False  # InvalidHandle 방지 — 콜백 진입 차단
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PersonTrackingNode()
    # MultiThreadedExecutor — 이미지 콜백(무거운)과 제어 콜백(가벼운)을 별도 스레드에서 실행.
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
