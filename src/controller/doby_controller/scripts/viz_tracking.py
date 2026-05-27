#!/usr/bin/env python3
"""
viz_tracking.py — 사람 탐지 + 그룹 클러스터링 실시간 시각화

구독: /robot_cam/image_raw/compressed  (카메라 원본)
      /person_tracking/tracks          (bbox + group_id + track_id)
      /person_tracking/approach_target (현재 접근 대상 그룹 id)

표시:
  - 각 그룹별 고유 색상 bbox
  - track_id / group_id 라벨
  - 접근 대상 그룹 ★ 표시
  - 좌상단: 총 인원 수 / 그룹 수 / 접근 타겟

실행: python3 scripts/viz_tracking.py
"""
from __future__ import annotations

import threading
import numpy as np
import cv2
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup

from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Int32
from dobi_npc_msgs.msg import PersonTrackArray

# 그룹별 색상 팔레트 (BGR)
GROUP_COLORS = [
    (0, 255, 0),    # 0: 초록
    (255, 100, 0),  # 1: 파랑
    (0, 100, 255),  # 2: 빨강
    (0, 255, 255),  # 3: 노랑
    (255, 0, 255),  # 4: 보라
    (0, 165, 255),  # 5: 주황
]
SOLO_COLOR   = (180, 180, 180)  # 그룹 없음: 회색
TARGET_COLOR = (0, 255, 255)    # 접근 타겟 강조: 노랑


class TrackingVizNode(Node):

    def __init__(self):
        super().__init__('tracking_viz_node')

        self._lock       = threading.Lock()
        self._frame      = None
        self._tracks     = []
        self._approach   = -1

        cg_img  = MutuallyExclusiveCallbackGroup()
        cg_ctrl = MutuallyExclusiveCallbackGroup()

        self.create_subscription(
            CompressedImage, '/robot_cam/image_raw/compressed',
            self._cb_img, 10, callback_group=cg_img)
        self.create_subscription(
            PersonTrackArray, '/person_tracking/tracks',
            self._cb_tracks, 10, callback_group=cg_ctrl)
        self.create_subscription(
            Int32, '/person_tracking/approach_target',
            self._cb_approach, 10, callback_group=cg_ctrl)

        self.get_logger().info('tracking_viz_node 준비 완료')

    def _cb_img(self, msg: CompressedImage):
        arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            with self._lock:
                self._frame = frame

    def _cb_tracks(self, msg: PersonTrackArray):
        with self._lock:
            self._tracks = list(msg.tracks)

    def _cb_approach(self, msg: Int32):
        with self._lock:
            self._approach = msg.data

    @staticmethod
    def _put_text(frame, text, pos, scale, color, thickness=2):
        """검정 아웃라인 + 컬러 텍스트 — 어떤 배경에서도 선명하게 보임."""
        cv2.putText(frame, text, pos,
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2)
        cv2.putText(frame, text, pos,
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)

    def get_viz_frame(self):
        with self._lock:
            if self._frame is None:
                return None
            frame    = self._frame.copy()
            tracks   = list(self._tracks)
            approach = self._approach

        H, W = frame.shape[:2]

        # 그룹별 인원 수 집계
        group_counts: dict[int, int] = {}
        for t in tracks:
            gid = t.group_id
            if gid >= 0:
                group_counts[gid] = group_counts.get(gid, 0) + 1

        # bbox 그리기
        for t in tracks:
            x1, y1, x2, y2 = [int(v) for v in t.bbox]
            gid  = t.group_id
            tid  = t.track_id
            is_target = (gid == approach and approach >= 0)

            # 색상 결정
            if is_target:
                color = TARGET_COLOR
                thick = 3
            elif gid >= 0:
                color = GROUP_COLORS[gid % len(GROUP_COLORS)]
                thick = 2
            else:
                color = SOLO_COLOR
                thick = 1

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)

            # 라벨: track_id / group (아웃라인 적용)
            label = f'track_id:{tid}'
            if gid >= 0:
                label += f'  group_id:{gid}({group_counts.get(gid, 1)}명)'
            if is_target:
                label += ' ★'

            label_y = max(y1 - 8, 16)
            self._put_text(frame, label, (x1, label_y), 0.55, color)

        # 좌상단 HUD
        total   = len(tracks)
        n_group = len(group_counts)
        hud1 = f'People: {total}  Groups: {n_group}'
        hud2 = f'Target: Group {approach}' if approach >= 0 else 'Target: none'

        # People/Groups — 밝은 초록
        self._put_text(frame, hud1, (10, 28), 0.7, (0, 230, 80))
        # Target — 타겟 있으면 노랑, 없으면 주황
        hud2_color = TARGET_COLOR if approach >= 0 else (0, 165, 255)
        self._put_text(frame, hud2, (10, 58), 0.7, hud2_color)

        return frame


def main():
    rclpy.init()
    node = TrackingVizNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)

    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    cv2.namedWindow('Tracking Viz', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Tracking Viz', 960, 540)

    # 대기 화면 (카메라/노드 준비 전)
    wait_frame = np.zeros((360, 640, 3), dtype=np.uint8)
    TrackingVizNode._put_text(wait_frame, 'Waiting for camera...', (160, 170), 0.8, (0, 230, 80))
    TrackingVizNode._put_text(wait_frame, 'YOLO loading (~8s)', (195, 210), 0.6, (0, 165, 255))

    try:
        while rclpy.ok():
            frame = node.get_viz_frame()
            if frame is not None:
                cv2.imshow('Tracking Viz', frame)
            else:
                cv2.imshow('Tracking Viz', wait_frame)
            key = cv2.waitKey(30)
            if key == 27 or key == ord('q'):  # ESC or q
                break
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
