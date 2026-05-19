from decimal import Decimal

from app.domain.table_assignment_runtime import StoreTable
from app.protocol.table_protocol import encode_table_payload


def test_encode_table_payload_serializes_table_number_and_status():
    payload = encode_table_payload(
        [
            StoreTable(1, 1, Decimal("0.000"), Decimal("0.000"), "empty"),
            StoreTable(2, 2, Decimal("0.000"), Decimal("0.000"), "occupied"),
        ]
    )

    assert payload == bytes([0, 0, 2, 0, 1, 0, 0, 2, 1])
