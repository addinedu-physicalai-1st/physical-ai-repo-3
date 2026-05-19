import pytest

from app.transport.tcp_receiver import TcpRequestHandler
from app.protocol.catalog_protocol import CatalogResponse, decode_catalog_payload
from app.protocol.header_protocol import (
    CMD_CATALOG,
    CMD_ORDER,
    CMD_TABLE,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    decode_header,
    encode_frame,
)
from app.protocol.order_protocol import OrderResponse, decode_order_response_payload
from app.protocol.table_protocol import TableAssignmentResponse, TableResponse
from app.domain.table_assignment_runtime import StoreTableDefinition, TableAssignmentRuntime


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
    request = FakeSocket(encode_frame(CMD_ORDER, METHOD_SET, 4, bytes([1, 0, 2, 3])))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)
    response = request.sent

    header = decode_header(response[:HEADER_SIZE])

    assert header.cmd_type == CMD_ORDER
    assert header.method == METHOD_SET
    assert header.sequence == 4
    assert decode_order_response_payload(response[HEADER_SIZE:]) == (True, 1001, None)
    assert len(server.orders) == 1
    assert [(item.product_id, item.quantity) for item in server.orders[0].items] == [(2, 3)]


def test_tcp_server_handles_table_request():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_TABLE, METHOD_GET, 8))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)
    response = request.sent

    header = decode_header(response[:HEADER_SIZE])

    assert header.cmd_type == CMD_TABLE
    assert header.method == METHOD_GET
    assert header.sequence == 8
    assert response[HEADER_SIZE:] == bytes([0, 0, 2, 0, 1, 0, 0, 2, 1])


def test_tcp_server_rejects_catalog_set_method():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_CATALOG, METHOD_SET, 5))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)

    assert request.sent == b""


def test_tcp_server_rejects_order_get_method():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_ORDER, METHOD_GET, 6, bytes([1, 0, 2, 3])))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)

    assert request.sent == b""
    assert server.orders == []


def test_tcp_server_handles_table_assignment_request():
    server = FakeServer()
    request = FakeSocket(encode_frame(CMD_TABLE, METHOD_SET, 7, bytes([0, 0, 3, 233, 1, 0, 2])))

    TcpRequestHandler(request, ("127.0.0.1", 12345), server)
    response = request.sent

    header = decode_header(response[:HEADER_SIZE])

    assert header.cmd_type == CMD_TABLE
    assert header.method == METHOD_SET
    assert header.sequence == 7
    assert response[HEADER_SIZE:] == bytes([0])
    assert server.assignments == [(1001, "dine_in", 2)]


class NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class FakeServer:
    def __init__(self):
        self.orders = []
        self.assignments = []
        self.table_runtime = TableAssignmentRuntime(
            [
                StoreTableDefinition(1, 1, 0, 0),
                StoreTableDefinition(2, 2, 0, 0),
            ]
        )
        self.table_runtime.occupy(2)
        self.name = "TestMocaService"
        self.logger = NullLogger()
        self.on_health = lambda seq: None
        self.on_status = lambda seq, peer: None
        self.on_catalog = lambda: CatalogResponse.ok({"menu": [], "allergy": [], "surcharges": {}})
        self.on_order = self._handle_order
        self.on_table = lambda: TableResponse.ok(self.table_runtime.list_tables())
        self.on_table_assignment = self._handle_table_assignment

    def _handle_order(self, request):
        self.orders.append(request)
        return OrderResponse.ok(1001)

    def _handle_table_assignment(self, request):
        self.assignments.append((request.order_id, request.receive_type, request.table_number))
        return TableAssignmentResponse.ok()


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
