from decimal import Decimal

from app.domain.table_assignment_runtime import StoreTable
from app.protocol.table_protocol import encode_table_payload, parse_table_assignment_payload


def test_encode_table_payload_serializes_table_number_and_status():
    payload = encode_table_payload(
        [
            StoreTable(3, 7, Decimal("0.000"), Decimal("0.000"), "empty"),
            StoreTable(4, 8, Decimal("0.000"), Decimal("0.000"), "occupied"),
        ]
    )

    assert payload == bytes([0, 0, 2, 0, 7, 0, 0, 8, 1])


def test_parse_table_assignment_payload_reads_big_endian_fields():
    request = parse_table_assignment_payload(bytes([0, 0, 3, 233, 1, 0, 2]))

    assert request.order_id == 1001
    assert request.receive_type == "dine_in"
    assert request.table_number == 2
