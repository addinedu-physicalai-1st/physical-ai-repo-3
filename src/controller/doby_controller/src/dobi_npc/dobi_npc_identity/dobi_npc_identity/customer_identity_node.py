"""customer_identity_node -- 얼굴 ReID 기반 영속 customer_id 부여 (P0).

/person_tracking/tracks 의 각 track bbox 에서 얼굴 임베딩을 추출하고
CustomerRegistry 로 customer_id 를 부여 -> /customer/registry 발행.
"""
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import Image
from std_msgs.msg import Header
from cv_bridge import CvBridge
from dobi_npc_msgs.msg import (
    PersonTrackArray, CustomerIdentity, CustomerRegistry,
)

from dobi_npc_identity.customer_registry import CustomerRegistry as Registry
from dobi_npc_identity.face_embedder import FaceEmbedder


class CustomerIdentityNode(Node):
    def __init__(self):
        super().__init__('customer_identity_node')
        self.declare_parameter('match_threshold', 0.5)
        self.declare_parameter('image_topic', '/webcam/image_raw')

        threshold = float(self.get_parameter('match_threshold').value)
        image_topic = str(self.get_parameter('image_topic').value)

        self._registry = Registry(match_threshold=threshold)
        self._embedder = FaceEmbedder()
        self._bridge = CvBridge()
        self._latest_bgr = None
        self._known_tracks: set = set()

        self.create_subscription(Image, image_topic, self._on_image, 10)
        self.create_subscription(
            PersonTrackArray, '/person_tracking/tracks', self._on_tracks, 10)
        self._pub = self.create_publisher(
            CustomerRegistry, '/customer/registry', 10)

        self.get_logger().info(
            f'customer_identity_node ready '
            f'(threshold={threshold}, image={image_topic})')

    def _on_image(self, msg: Image):
        try:
            self._latest_bgr = self._bridge.imgmsg_to_cv2(msg, 'bgr8')
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f'image 변환 실패: {e}')

    def _on_tracks(self, msg: PersonTrackArray):
        if self._latest_bgr is None:
            return

        current_ids: set = set()
        identities = []

        for track in msg.tracks:
            tid = int(track.track_id)
            current_ids.add(tid)

            cid = self._registry.resolve_no_face(tid)
            if cid is not None:
                conf = 1.0
            else:
                emb = self._embedder.embed_in_roi(
                    self._latest_bgr, track.bbox)
                if emb is None:
                    continue  # 얼굴 아직 못 잡음 -- 이번 프레임 skip
                cid, conf = self._registry.resolve(tid, emb)
                self.get_logger().info(
                    f'track {tid} -> customer {cid} (conf={conf:.2f})')

            ident = CustomerIdentity()
            ident.track_id = tid
            ident.customer_id = cid
            ident.reid_confidence = float(conf)
            ident.blocklisted = False       # P1
            ident.outcome = 'untouched'     # P1
            identities.append(ident)

        for gone in self._known_tracks - current_ids:
            self._registry.release_track(gone)
        self._known_tracks = current_ids

        reg_msg = CustomerRegistry()
        reg_msg.header = Header()
        reg_msg.header.stamp = self.get_clock().now().to_msg()
        reg_msg.customers = identities
        self._pub.publish(reg_msg)


def main(args=None):
    rclpy.init(args=args)
    node = CustomerIdentityNode()
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
