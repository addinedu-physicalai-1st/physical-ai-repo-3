"""approach_controller_node /approach/enable 게이트 단위 테스트."""
import time
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, Int32
from geometry_msgs.msg import Twist, PoseStamped

from person_tracking_pkg.approach_controller_node import ApproachControllerNode

# 노드가 BEST_EFFORT 로 발행하므로 구독도 동일 QoS 사용
_CMD_VEL_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def test_disable_default_no_publish(ros_context):
    """기본 상태 (enable=False) 에서 cmd_vel 발행 안 함."""
    node = ApproachControllerNode()

    received = []
    sub_node = rclpy.create_node('test_sub')
    sub_node.create_subscription(
        Twist, '/bt/cmd_vel', lambda m: received.append(m), _CMD_VEL_QOS)
    pub_target = sub_node.create_publisher(Int32, '/person_tracking/approach_target', 10)
    pub_pose = sub_node.create_publisher(PoseStamped, '/customer_pose', 10)

    target_msg = Int32(); target_msg.data = 0; pub_target.publish(target_msg)
    pose_msg = PoseStamped()
    pose_msg.pose.position.x = 0.3
    pose_msg.pose.position.y = 0.5
    pose_msg.pose.position.z = 0.4
    pub_pose.publish(pose_msg)

    exec_ = SingleThreadedExecutor()
    exec_.add_node(node)
    exec_.add_node(sub_node)

    start = time.time()
    while time.time() - start < 2.0:
        exec_.spin_once(timeout_sec=0.1)

    node.destroy_node()
    sub_node.destroy_node()

    assert len(received) == 0, f"enable=False 이지만 {len(received)} 회 cmd_vel 발행됨"


def test_enable_true_then_publish(ros_context):
    """enable=True 토글 후 cmd_vel 발행."""
    node = ApproachControllerNode()

    received = []
    sub_node = rclpy.create_node('test_sub2')
    sub_node.create_subscription(
        Twist, '/bt/cmd_vel', lambda m: received.append(m), _CMD_VEL_QOS)
    pub_target = sub_node.create_publisher(Int32, '/person_tracking/approach_target', 10)
    pub_pose = sub_node.create_publisher(PoseStamped, '/customer_pose', 10)
    pub_enable = sub_node.create_publisher(Bool, '/approach/enable', 10)

    target_msg = Int32(); target_msg.data = 0; pub_target.publish(target_msg)
    pose_msg = PoseStamped()
    pose_msg.pose.position.x = 0.3
    pose_msg.pose.position.y = 0.5
    pose_msg.pose.position.z = 0.4
    pub_pose.publish(pose_msg)
    enable_msg = Bool(); enable_msg.data = True; pub_enable.publish(enable_msg)

    exec_ = SingleThreadedExecutor()
    exec_.add_node(node)
    exec_.add_node(sub_node)

    start = time.time()
    while time.time() - start < 2.0:
        exec_.spin_once(timeout_sec=0.1)

    node.destroy_node()
    sub_node.destroy_node()

    assert len(received) > 0, "enable=True 이지만 cmd_vel 미발행"
