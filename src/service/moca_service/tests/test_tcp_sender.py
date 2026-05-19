from types import SimpleNamespace

from app.transport.tcp_sender import TcpEndpoint, TcpSender, build_moca_tcp_sender


def test_tcp_sender_sends_frame_to_named_endpoint(monkeypatch):
    sent = []
    sender = TcpSender(
        {"AdminGUI": TcpEndpoint("127.0.0.1", 9000, "AdminGUI")},
        NullLogger(),
    )

    monkeypatch.setattr("app.transport.tcp_sender.socket.create_connection", fake_create_connection(sent))

    assert sender.send_frame("AdminGUI", b"frame") is True
    assert sent == [(("127.0.0.1", 9000), 3.0, b"frame")]


def test_tcp_sender_broadcasts_to_default_targets(monkeypatch):
    sent = []
    sender = TcpSender(
        {
            "AdminGUI": TcpEndpoint("127.0.0.1", 9000, "AdminGUI"),
            "WebService": TcpEndpoint("127.0.0.1", 9004, "WebService"),
        },
        NullLogger(),
        default_targets=["WebService", "AdminGUI"],
    )

    monkeypatch.setattr("app.transport.tcp_sender.socket.create_connection", fake_create_connection(sent))

    assert sender.broadcast_frame(b"status") == {"WebService": True, "AdminGUI": True}
    assert sent == [
        (("127.0.0.1", 9004), 3.0, b"status"),
        (("127.0.0.1", 9000), 3.0, b"status"),
    ]


def test_tcp_sender_broadcast_continues_after_endpoint_failure(monkeypatch):
    sent = []
    sender = TcpSender(
        {
            "AdminGUI": TcpEndpoint("127.0.0.1", 9000, "AdminGUI"),
            "WebService": TcpEndpoint("127.0.0.1", 9004, "WebService"),
        },
        NullLogger(),
        default_targets=["AdminGUI", "WebService"],
    )

    monkeypatch.setattr(
        "app.transport.tcp_sender.socket.create_connection",
        fake_create_connection(sent, failing_address=("127.0.0.1", 9000)),
    )

    assert sender.broadcast_frame(b"status") == {"AdminGUI": False, "WebService": True}
    assert sent == [(("127.0.0.1", 9004), 3.0, b"status")]


def test_build_moca_tcp_sender_uses_configured_endpoints():
    sender = build_moca_tcp_sender(
        SimpleNamespace(
            admin_gui_host="admin",
            admin_gui_port=9000,
            web_service_host="web",
            web_service_tcp_port=9004,
            cooking_controller_bridge_host="cooking",
            cooking_controller_bridge_port=9005,
            serving_controller_bridge_host="serving",
            serving_controller_bridge_port=9006,
        ),
        NullLogger(),
    )

    assert list(sender.endpoints) == [
        "AdminGUI",
        "WebService",
        "CookingControllerBridge",
        "ServingControllerBridge",
    ]
    assert sender.endpoints["WebService"] == TcpEndpoint("web", 9004, "WebService")
    assert sender.default_targets == list(sender.endpoints)


def fake_create_connection(sent, failing_address=None):
    def create_connection(address, timeout):
        if address == failing_address:
            raise OSError("unavailable")
        return FakeSocket(sent, address, timeout)

    return create_connection


class FakeSocket:
    def __init__(self, sent, address, timeout):
        self.sent = sent
        self.address = address
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def sendall(self, frame):
        self.sent.append((self.address, self.timeout, frame))


class NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass
