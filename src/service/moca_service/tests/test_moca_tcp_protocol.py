import pytest

from app.tcp import TcpRequestHandler
from app.protocol.moca_protocol import (
    CMD_CATALOG,
    CMD_ORDER,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    decode_catalog_payload,
    decode_header,
    decode_order_response_payload,
    encode_frame,
)


def test_moca_tcp_header_round_trip():
    frame = encode_frame(CMD_CATALOG, METHOD_GET, 9, b"abc")

    header = decode_header(frame[:HEADER_SIZE])

    assert header.cmd_type == CMD_CATALOG
    assert header.method == METHOD_GET
    assert header.sequence == 9
    assert header.payload_size == 3


def test_moca_tcp_rejects_unknown_command():
    with pytest.raises(ValueError):
        decode_header(bytes([0x99, METHOD_GET, 1, 0, 0, 0, 0]))


def test_tcp_server_handles_catalog_request():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_CATALOG, METHOD_GET, 3))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)
    response = request.sent

    header = decode_header(response[:HEADER_SIZE])

    assert header.cmd_type == CMD_CATALOG
    assert header.method == METHOD_GET
    assert header.sequence == 3
    assert decode_catalog_payload(response[HEADER_SIZE:]) == {"menu": [], "allergy": [], "surcharges": {}}


def test_tcp_server_handles_order_request():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_ORDER, METHOD_SET, 4, bytes([1, 7, 1, 0, 2, 3])))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)
    response = request.sent

    header = decode_header(response[:HEADER_SIZE])

    assert header.cmd_type == CMD_ORDER
    assert header.method == METHOD_SET
    assert header.sequence == 4
    assert decode_order_response_payload(response[HEADER_SIZE:]) == (True, None)
    assert len(server.orders) == 1
    assert server.orders[0].receive_type == 1
    assert server.orders[0].table_id == 7
    assert [(item.product_id, item.quantity) for item in server.orders[0].items] == [(2, 3)]


def test_tcp_server_rejects_catalog_set_method():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_CATALOG, METHOD_SET, 5))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)

    assert request.sent == b""


def test_tcp_server_rejects_order_get_method():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_ORDER, METHOD_GET, 6, bytes([1, 7, 1, 0, 2, 3])))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)

    assert request.sent == b""
    assert server.orders == []


class NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class FakeServer:
    def __init__(self):
        self.orders = []
        self.name = "TestMocaService"
        self.logger = NullLogger()
        self.on_health = lambda seq: None
        self.on_status = lambda seq, peer: None
        self.on_catalog = lambda: {"menu": [], "allergy": [], "surcharges": {}}
        self.on_order = self.orders.append


class FakeSocket:
    def __init__(self, incoming: bytes):
        self.incoming = bytearray(incoming)
        self.sent = bytearray()

    def recv(self, size: int) -> bytes:
        if not self.incoming:
            return b""
        chunk = self.incoming[:size]
        del self.incoming[:size]
        return bytes(chunk)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)
