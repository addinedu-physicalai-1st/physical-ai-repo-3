import pytest

from app.protocol.business_tcp import (
    HEADER_SIZE,
    TYPE_CATALOG_REQUEST,
    VERSION,
    decode_header,
    decode_payload,
    encode_message,
)


def test_business_tcp_encode_decode_round_trip():
    frame = encode_message(TYPE_CATALOG_REQUEST, 7, {"resource": "catalog"})

    message_type, request_id, payload_size = decode_header(frame[:HEADER_SIZE])
    payload = decode_payload(frame[HEADER_SIZE:])

    assert message_type == TYPE_CATALOG_REQUEST
    assert request_id == 7
    assert payload_size == len(frame) - HEADER_SIZE
    assert payload == {"resource": "catalog"}


def test_business_tcp_rejects_invalid_magic():
    frame = bytearray(encode_message(TYPE_CATALOG_REQUEST, 7, {"resource": "catalog"}))
    frame[0] = 0x00

    with pytest.raises(ValueError):
        decode_header(bytes(frame[:HEADER_SIZE]))


def test_business_tcp_rejects_invalid_version():
    frame = bytearray(encode_message(TYPE_CATALOG_REQUEST, 7, {"resource": "catalog"}))
    frame[2] = VERSION + 1

    with pytest.raises(ValueError):
        decode_header(bytes(frame[:HEADER_SIZE]))
