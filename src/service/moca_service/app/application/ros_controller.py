import logging

from app.transport.ros_server import RosServer


class MocaRosController:
    def __init__(self, ros_server: RosServer, logger: logging.Logger):
        self.ros_server = ros_server
        self.logger = logger

    def publish_health_status(self, seq: int) -> None:
        published = self.ros_server.publish_status(seq)
        if published:
            self.logger.info("moca_service ROS health status published seq=%s", seq)
