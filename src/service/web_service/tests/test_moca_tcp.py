import pytest

from app.clients.moca_tcp_client import (
    MocaOrderItem,
    MocaOrderRejected,
    MocaTableAssignmentRejected,
    MocaTcpCatalogClient,
    MocaTcpOrderClient,
    MocaTcpTableClient,
)
from app.protocol.header_protocol import (
    CMD_CATALOG,
    CMD_ORDER,
    CMD_TABLE,
    ERROR_TABLE_ASSIGNMENT_REJECTED,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    decode_header,
    encode_error_payload,
    encode_frame,
)
from app.protocol.catalog_protocol import decode_catalog_payload, encode_catalog_payload
from app.protocol.order_protocol import encode_order_success_payload
from app.protocol.table_protocol import decode_table_payload, encode_table_assignment_request_payload


def test_moca_tcp_header_round_trip():
    frame = encode_frame(CMD_CATALOG, METHOD_GET, 7, b"abc")

    header = decode_header(frame[:HEADER_SIZE])

    assert header.cmd_type == CMD_CATALOG
    assert header.method == METHOD_GET
    assert header.sequence == 7
    assert header.payload_size == 3
    assert frame[HEADER_SIZE:] == b"abc"


def test_moca_tcp_rejects_large_payload_size():
    with pytest.raises(ValueError):
        decode_header(bytes([CMD_CATALOG, METHOD_GET, 1, 0, 16, 0, 1]))


def test_moca_tcp_clients_send_catalog_and_order_requests(monkeypatch):
    requests = []
    sockets = []

    def create_connection(address, timeout):
        fake_socket = FakeSocket(requests)
        fake_socket.connect_calls += 1
        sockets.append(fake_socket)
        return fake_socket

    monkeypatch.setattr("socket.create_connection", create_connection)
    catalog_client = MocaTcpCatalogClient("127.0.0.1", 9001, timeout_sec=1.0)
    order_client = MocaTcpOrderClient("127.0.0.1", 9001, timeout_sec=1.0)

    catalog = catalog_client.fetch_catalog()
    order_id = order_client.create_order([MocaOrderItem(product_id=258, quantity=3)])
    catalog_client.close()
    order_client.close()

    assert catalog == {"menu": [], "allergy": [], "surcharges": {}}
    assert order_id == 1001
    assert len(sockets) == 2
    assert len(requests) == 2
    assert [request[0].cmd_type for request in requests] == [CMD_CATALOG, CMD_ORDER]
    assert [request[0].method for request in requests] == [METHOD_GET, METHOD_SET]
    assert requests[0][0].sequence == 1
    assert requests[1][0].sequence == 1
    assert requests[1][1] == bytes([1, 1, 2, 3])


def test_moca_tcp_table_client_sends_table_request(monkeypatch):
    requests = []

    def create_connection(address, timeout):
        return FakeSocket(requests)

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpTableClient("127.0.0.1", 9001, timeout_sec=1.0)

    tables = client.fetch_tables()

    assert tables == [{"id": 1, "status": "empty"}, {"id": 2, "status": "occupied"}]
    assert len(requests) == 1
    assert requests[0][0].cmd_type == CMD_TABLE
    assert requests[0][0].method == METHOD_GET
    assert requests[0][1] == b""
    client.close()


def test_moca_tcp_table_client_sends_assignment_request(monkeypatch):
    requests = []

    def create_connection(address, timeout):
        return FakeSocket(requests)

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpTableClient("127.0.0.1", 9001, timeout_sec=1.0)

    client.assign_table(1001, "dine_in", 2)

    assert len(requests) == 1
    assert requests[0][0].cmd_type == CMD_TABLE
    assert requests[0][0].method == METHOD_SET
    assert requests[0][1] == encode_table_assignment_request_payload(1001, "dine_in", 2)
    client.close()


def test_moca_tcp_table_client_maps_assignment_rejection(monkeypatch):
    fake_socket = FakeSocket([], table_assignment_error=True)

    def create_connection(address, timeout):
        return fake_socket

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpTableClient("127.0.0.1", 9001, timeout_sec=1.0)

    with pytest.raises(MocaTableAssignmentRejected):
        client.assign_table(1001, "dine_in", 2)
    client.close()


def test_moca_tcp_client_maps_order_error_to_rejected(monkeypatch):
    fake_socket = FakeSocket([], order_error=True)

    def create_connection(address, timeout):
        return fake_socket

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpOrderClient("127.0.0.1", 9001, timeout_sec=1.0)

    with pytest.raises(MocaOrderRejected):
        client.create_order([MocaOrderItem(product_id=1, quantity=1)])
    client.close()


def test_moca_tcp_catalog_payload_round_trip():
    catalog = {
        "menu": [
            {
                "id": 1,
                "name": "아메리카노",
                "emoji": "☕",
                "price": 3500,
                "hot": True,
                "shot": True,
                "ice": True,
                "milk": False,
            }
        ],
        "allergy": [{"name": "유제품", "icon": "🥛", "items": ["아메리카노"]}],
        "surcharges": {"shot:추가": 500},
    }

    assert decode_catalog_payload(encode_catalog_payload(catalog)) == catalog


def test_moca_tcp_table_payload_decode_round_trip():
    payload = bytes([0, 0, 2, 0, 1, 0, 0, 2, 1])

    assert decode_table_payload(payload) == [{"id": 1, "status": "empty"}, {"id": 2, "status": "occupied"}]


class FakeSocket:
    def __init__(self, requests, order_error=False, table_assignment_error=False):
        self.requests = requests
        self.order_error = order_error
        self.table_assignment_error = table_assignment_error
        self.connect_calls = 0
        self.response = bytearray()
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        header = decode_header(data[:HEADER_SIZE])
        payload = data[HEADER_SIZE:]
        self.requests.append((header, payload))

        if header.cmd_type == CMD_CATALOG:
            response = encode_catalog_payload({"menu": [], "allergy": [], "surcharges": {}})
            self.response.extend(encode_frame(CMD_CATALOG, METHOD_GET, header.sequence, response))
        elif header.cmd_type == CMD_ORDER and self.order_error:
            response = encode_error_payload(2, "bad order")
            self.response.extend(encode_frame(CMD_ORDER, METHOD_SET, header.sequence, response))
        elif header.cmd_type == CMD_ORDER:
            self.response.extend(
                encode_frame(CMD_ORDER, METHOD_SET, header.sequence, encode_order_success_payload(1001))
            )
        elif header.cmd_type == CMD_TABLE and header.method == METHOD_GET:
            response = bytes([0, 0, 2, 0, 1, 0, 0, 2, 1])
            self.response.extend(encode_frame(CMD_TABLE, METHOD_GET, header.sequence, response))
        elif header.cmd_type == CMD_TABLE and self.table_assignment_error:
            response = encode_error_payload(ERROR_TABLE_ASSIGNMENT_REJECTED, "table occupied")
            self.response.extend(encode_frame(CMD_TABLE, METHOD_SET, header.sequence, response))
        elif header.cmd_type == CMD_TABLE:
            self.response.extend(encode_frame(CMD_TABLE, METHOD_SET, header.sequence, bytes([0])))

    def recv(self, size):
        if not self.response:
            return b""
        chunk = self.response[:size]
        del self.response[:size]
        return bytes(chunk)

    def close(self):
        self.closed = True
