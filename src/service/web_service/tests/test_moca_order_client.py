import pytest

from app.clients.moca_order_client import MocaOrderItem, encode_order_request


def test_encode_order_request_uses_big_endian_product_id():
    frame = encode_order_request(
        1,
        7,
        [MocaOrderItem(product_id=1, quantity=2), MocaOrderItem(product_id=258, quantity=3)],
    )

    assert frame == bytes([1, 7, 2, 0, 1, 2, 1, 2, 3])


def test_encode_order_request_rejects_empty_items():
    with pytest.raises(ValueError):
        encode_order_request(0, 0, [])
