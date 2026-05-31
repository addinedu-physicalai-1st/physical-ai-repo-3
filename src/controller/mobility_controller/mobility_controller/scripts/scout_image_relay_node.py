#!/usr/bin/env python3
"""scout_image_relay — scout_cam 영상을 팀 표준 토픽명으로 미러 (방향 (나)).

scout_reactor(call_detector/palm_gesture)는 /scout_cam/image_raw 를 그대로 사용해
lock-on 파이프라인이 무손상이고, person_tracking(팀 표준)은 /robot_cam/image_raw 를
구독한다. 단일 카메라 grab 은 그대로 두고 토픽명만 통일하기 위한 relay.

구독: <in_topic>            (sensor_msgs/Image)        — relay_raw=True 시
      <in_topic>/compressed (sensor_msgs/CompressedImage) — relay_compressed=True 시
발행: <out_topic>            / <out_topic>/compressed

통합 모드(팀이 /robot_cam/image_raw 를 직접 발행)에서는 launch 의
relay_scout_image:=false 로 본 노드를 띄우지 않는다(이중 발행 방지).
"""
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import Image, CompressedImage


class ScoutImageRelay(Node):
    def __init__(self):
        super().__init__('scout_image_relay')
        self.declare_parameter('in_topic', '/scout_cam/image_raw')
        self.declare_parameter('out_topic', '/robot_cam/image_raw')
        self.declare_parameter('relay_raw', True)
        self.declare_parameter('relay_compressed', True)

        in_t = str(self.get_parameter('in_topic').value)
        out_t = str(self.get_parameter('out_topic').value)
        relay_raw = bool(self.get_parameter('relay_raw').value)
        relay_compressed = bool(self.get_parameter('relay_compressed').value)

        # QoS depth 10 reliable — scout_cam 발행 및 person_tracking 구독과 동일(검증됨).
        if relay_raw:
            self._pub_raw = self.create_publisher(Image, out_t, 10)
            self.create_subscription(Image, in_t, self._pub_raw.publish, 10)
        if relay_compressed:
            self._pub_comp = self.create_publisher(
                CompressedImage, out_t + '/compressed', 10)
            self.create_subscription(
                CompressedImage, in_t + '/compressed', self._pub_comp.publish, 10)

        kinds = ','.join(
            k for k, on in (('raw', relay_raw), ('compressed', relay_compressed)) if on)
        self.get_logger().info(f'scout_image_relay ready: {in_t} → {out_t} ({kinds})')


def main(args=None):
    rclpy.init(args=args)
    node = ScoutImageRelay()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
