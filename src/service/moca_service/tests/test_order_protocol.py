import pytest

from app.protocol.order_protocol import parse_order_request


def test_parse_order_request_reads_big_endian_product_ids():
    request = parse_order_request(
        bytes([2]),
        bytes([0, 1, 2, 1, 2, 3]),
    )

    assert [(item.product_id, item.quantity) for item in request.items] == [(1, 2), (258, 3)]


def test_parse_order_request_rejects_empty_items():
    with pytest.raises(ValueError):
        parse_order_request(bytes([0]), b"")
