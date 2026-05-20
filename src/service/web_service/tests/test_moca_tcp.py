import logging

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
    CMD_ALLERGY,
    CMD_MENU,
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
from app.protocol.catalog_protocol import (
    decode_allergy_payload,
    decode_menu_option_payload,
    encode_allergy_payload,
    encode_menu_option_payload,
)
from app.protocol.order_protocol import encode_order_success_payload
from app.protocol.table_protocol import decode_table_payload, encode_table_assignment_request_payload


def test_moca_tcp_header_round_trip():
    frame = encode_frame(CMD_MENU, METHOD_GET, 7, b"abc")

    header = decode_header(frame[:HEADER_SIZE])

    assert header.cmd_type == CMD_MENU
    assert header.method == METHOD_GET
    assert header.sequence == 7
    assert header.payload_size == 3
    assert frame[HEADER_SIZE:] == b"abc"


def test_moca_tcp_rejects_large_payload_size():
    with pytest.raises(ValueError):
        decode_header(bytes([CMD_MENU, METHOD_GET, 1, 0, 16, 0, 1]))


def test_moca_tcp_clients_send_catalog_and_order_requests(monkeypatch, caplog):
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

    with caplog.at_level(logging.INFO, logger="web_service"):
        catalog = catalog_client.fetch_catalog()
        order_id = order_client.create_order([MocaOrderItem(product_id=258, quantity=3)])
    catalog_client.close()
    order_client.close()

    assert catalog == {"menu": [], "allergy": [], "surcharges": {}}
    assert order_id == 1001
    assert len(sockets) == 2
    assert len(requests) == 3
    assert [request[0].cmd_type for request in requests] == [CMD_MENU, CMD_ALLERGY, CMD_ORDER]
    assert [request[0].method for request in requests] == [METHOD_GET, METHOD_GET, METHOD_SET]
    assert requests[0][0].sequence == 1
    assert requests[0][1] == b""
    assert requests[1][0].sequence == 2
    assert requests[1][1] == b""
    assert requests[2][0].sequence == 1
    assert requests[2][1] == bytes([1, 1, 2, 3])
    payload_logs = [record.message for record in caplog.records if "parsed MOCA response payload" in record.message]
    assert payload_logs
    assert any("'menu': []" in message for message in payload_logs)
    assert any("'allergy': []" in message for message in payload_logs)
    assert any("'status': 'ok', 'order_id': 1001" in message for message in payload_logs)
    assert all("cmd_type" not in message for message in payload_logs)
    assert all("payload_size" not in message for message in payload_logs)


def test_moca_tcp_catalog_client_sends_menu_option_request(monkeypatch):
    requests = []

    def create_connection(address, timeout):
        return FakeSocket(requests)

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpCatalogClient("127.0.0.1", 9001, timeout_sec=1.0)

    menu_options = client.fetch_menu_options()

    assert menu_options == {"menu": []}
    assert len(requests) == 1
    assert requests[0][0].cmd_type == CMD_MENU
    assert requests[0][0].method == METHOD_GET
    assert requests[0][1] == b""
    client.close()


def test_moca_tcp_catalog_client_sends_allergy_request(monkeypatch):
    requests = []

    def create_connection(address, timeout):
        return FakeSocket(requests)

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpCatalogClient("127.0.0.1", 9001, timeout_sec=1.0)

    allergy = client.fetch_allergy()

    assert allergy == {"allergy": []}
    assert len(requests) == 1
    assert requests[0][0].cmd_type == CMD_ALLERGY
    assert requests[0][0].method == METHOD_GET
    assert requests[0][1] == b""
    client.close()


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


def test_moca_tcp_table_client_sends_assignment_request(monkeypatch, caplog):
    requests = []

    def create_connection(address, timeout):
        return FakeSocket(requests)

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpTableClient("127.0.0.1", 9001, timeout_sec=1.0)

    with caplog.at_level(logging.INFO, logger="web_service"):
        client.assign_table(1001, "dine_in", 2)

    assert len(requests) == 1
    assert requests[0][0].cmd_type == CMD_TABLE
    assert requests[0][0].method == METHOD_SET
    assert requests[0][1] == encode_table_assignment_request_payload(1001, "dine_in", 2)
    payload_logs = [record.message for record in caplog.records if "parsed MOCA response payload" in record.message]
    assert payload_logs
    assert "'status': 'ok'" in payload_logs[-1]
    assert "sequence" not in payload_logs[-1]
    assert "payload_size" not in payload_logs[-1]
    client.close()


def test_moca_tcp_table_client_maps_assignment_rejection(monkeypatch, caplog):
    fake_socket = FakeSocket([], table_assignment_error=True)

    def create_connection(address, timeout):
        return fake_socket

    monkeypatch.setattr("socket.create_connection", create_connection)
    client = MocaTcpTableClient("127.0.0.1", 9001, timeout_sec=1.0)

    with caplog.at_level(logging.INFO, logger="web_service"):
        with pytest.raises(MocaTableAssignmentRejected):
            client.assign_table(1001, "dine_in", 2)
    payload_logs = [record.message for record in caplog.records if "parsed MOCA response payload" in record.message]
    assert payload_logs
    assert "'status': 'error'" in payload_logs[-1]
    assert "'error_code': 5" in payload_logs[-1]
    assert "'message': 'table occupied'" in payload_logs[-1]
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


def test_moca_tcp_menu_option_payload_round_trip():
    catalog = {
        "menu": [
            {
                "id": 1,
                "name": "아메리카노",
                "image": "☕",
                "price": 3500,
                "options": [
                    {"option_group": "온도", "option_name": "HOT", "price": 0, "is_default": True},
                    {"option_group": "온도", "option_name": "ICE", "price": 0, "is_default": False},
                    {"option_group": "에스프레소 샷", "option_name": "추가", "price": 500, "is_default": False},
                ],
            }
        ]
    }

    assert decode_menu_option_payload(encode_menu_option_payload(catalog)) == catalog["menu"]


def test_moca_tcp_allergy_payload_round_trip():
    catalog = {"allergy": [{"name": "유제품", "icon": "🥛", "items": ["아메리카노"]}]}

    assert decode_allergy_payload(encode_allergy_payload(catalog)) == catalog["allergy"]


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

        if header.cmd_type == CMD_MENU:
            response = encode_menu_option_payload({"menu": []})
            self.response.extend(encode_frame(CMD_MENU, METHOD_GET, header.sequence, response))
        elif header.cmd_type == CMD_ALLERGY:
            response = encode_allergy_payload({"allergy": []})
            self.response.extend(encode_frame(CMD_ALLERGY, METHOD_GET, header.sequence, response))
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
