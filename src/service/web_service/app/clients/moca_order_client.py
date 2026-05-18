import socket
import struct
from dataclasses import dataclass
from typing import Protocol


ACK = 0x06
NAK = 0x15
MAX_U8 = 0xFF
MAX_U16 = 0xFFFF


@dataclass(frozen=True)
class MocaOrderItem:
    product_id: int
    quantity: int


class OrderClient(Protocol):
    def create_order(self, receive_type: int, table_id: int, items: list[MocaOrderItem]) -> None:
        ...


class MocaOrderClientError(RuntimeError):
    pass


class MocaOrderRejected(MocaOrderClientError):
    pass


class MocaOrderClient:
    def __init__(self, host: str, port: int, timeout_sec: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec

    def create_order(self, receive_type: int, table_id: int, items: list[MocaOrderItem]) -> None:
        frame = encode_order_request(receive_type, table_id, items)

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_sec) as sock:
                sock.settimeout(self.timeout_sec)
                sock.sendall(frame)
                response = sock.recv(1)
        except OSError as exc:
            raise MocaOrderClientError(
                f"moca_service order request failed: {self.host}:{self.port}: {exc}"
            ) from exc

        if response != bytes([ACK]):
            if response == bytes([NAK]):
                raise MocaOrderRejected("moca_service rejected order request")
            raise MocaOrderClientError(f"unexpected moca_service order response: {response.hex(' ')}")


def encode_order_request(receive_type: int, table_id: int, items: list[MocaOrderItem]) -> bytes:
    if receive_type not in {0, 1}:
        raise ValueError(f"invalid receive_type={receive_type}")
    if not 0 <= table_id <= MAX_U8:
        raise ValueError(f"invalid table_id={table_id}")
    if not 1 <= len(items) <= MAX_U8:
        raise ValueError(f"invalid item_count={len(items)}")

    frame = bytearray([receive_type, table_id, len(items)])
    for item in items:
        if not 1 <= item.product_id <= MAX_U16:
            raise ValueError(f"invalid product_id={item.product_id}")
        if not 1 <= item.quantity <= MAX_U8:
            raise ValueError(f"invalid quantity={item.quantity}")
        frame.extend(struct.pack(">HB", item.product_id, item.quantity))
    return bytes(frame)
