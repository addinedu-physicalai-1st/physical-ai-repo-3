import logging

from app.communication.admin_gui.publisher import AdminGuiPublisher, TcpEndpoint
from app.communication.admin_gui.runtime import AdminGuiCommunicationRuntime
from app.communication.admin_gui.subscriber import AdminGuiSubscriber


def create_admin_gui_communication_runtime(
    *,
    listen_host: str,
    listen_port: int,
    peer_host: str,
    peer_port: int,
    logger: logging.Logger,
    peer_name: str = "AdminGUI",
    timeout: float = 3.0,
) -> AdminGuiCommunicationRuntime:
    runtime_holder: dict[str, AdminGuiCommunicationRuntime] = {}

    def handle_frame(frame, peer):
        runtime_holder["runtime"].handle_frame(frame, peer)

    publisher = AdminGuiPublisher(
        TcpEndpoint(peer_host, peer_port, peer_name),
        logger,
        timeout=timeout,
    )
    subscriber = AdminGuiSubscriber(
        listen_host,
        listen_port,
        handle_frame,
        logger,
        name="moca-admin-gui-subscriber",
    )
    runtime = AdminGuiCommunicationRuntime(
        subscriber=subscriber,
        publisher=publisher,
        logger=logger,
    )
    runtime_holder["runtime"] = runtime
    return runtime
