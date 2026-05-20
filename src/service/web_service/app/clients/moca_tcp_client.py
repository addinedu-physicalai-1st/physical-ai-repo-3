import logging
import socket
import threading
from typing import Any

from app.protocol.header_protocol import (
    CMD_ALLERGY,
    CMD_MENU,
    CMD_ORDER,
    CMD_TABLE,
    ERROR_ORDER_NOT_FOUND,
    ERROR_TABLE_ASSIGNMENT_REJECTED,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    STATUS_ERROR,
    STATUS_OK,
    MocaHeader,
    decode_error_payload,
    decode_header,
    encode_frame,
)
from app.protocol.catalog_protocol import (
    decode_catalog_payload,
)
from app.protocol.order_protocol import (
    MocaOrderItem,
    decode_order_response_payload,
    encode_order_request_payload,
)
from app.protocol.table_protocol import (
    ReceiveType,
    decode_table_assignment_response_payload,
    decode_table_payload,
    encode_table_assignment_request_payload,
)


class MocaCatalogClientError(RuntimeError):
    pass


class MocaOrderClientError(RuntimeError):
    pass


class MocaOrderRejected(MocaOrderClientError):
    pass


class MocaTableClientError(RuntimeError):
    pass


class MocaTableAssignmentNotFound(MocaTableClientError):
    pass


class MocaTableAssignmentRejected(MocaTableClientError):
    pass


class MocaTcpBaseClient:
    """Persistent TCP client for MOCA request/response frames.

    The wire format is:
    [7-byte MOCA header][command-specific raw binary payload].
    This base class owns connection reuse, sequence numbers, exact reads,
    and response header validation. Subclasses only encode/decode payloads.
    """

    def __init__(self, host: str, port: int, timeout_sec: float = 3.0):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec
        self._lock = threading.Lock()
        self._sequence = 0
        self._sock: socket.socket | None = None
        self._logger = logging.getLogger("web_service")

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def request(self, cmd_type: int, method: int, payload: bytes) -> tuple[MocaHeader, bytes]:
        """Send one MOCA frame and return the validated response payload."""

        with self._lock:
            sequence = self._next_sequence_unlocked()
            sock = self._connect_unlocked()
            sock.sendall(encode_frame(cmd_type, method, sequence, payload))

            header = decode_header(self._read_exact_unlocked(HEADER_SIZE))
            if header.cmd_type != cmd_type:
                raise ValueError(f"moca response cmd_type mismatch: {header.cmd_type} != {cmd_type}")
            if header.method != method:
                raise ValueError(f"moca response method mismatch: {header.method} != {method}")
            if header.sequence != sequence:
                raise ValueError(f"moca response sequence mismatch: {header.sequence} != {sequence}")

            response_payload = self._read_exact_unlocked(header.payload_size)
            self._logger.info(
                "parsed MOCA response payload from moca_service: %s",
                _parse_received_response_payload(header, response_payload),
            )
            return header, response_payload

    def _next_sequence_unlocked(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFF
        return self._sequence

    def _connect_unlocked(self) -> socket.socket:
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout_sec)
            self._sock.settimeout(self.timeout_sec)
        return self._sock

    def _close_unlocked(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        finally:
            self._sock = None

    def _read_exact_unlocked(self, size: int) -> bytes:
        """Read exactly size bytes so TCP packet boundaries do not leak upward."""

        chunks = bytearray()
        while len(chunks) < size:
            sock = self._connect_unlocked()
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                self._close_unlocked()
                raise OSError(f"incomplete tcp read: {len(chunks)} of {size} bytes")
            chunks.extend(chunk)
        return bytes(chunks)


class MocaTcpCatalogClient(MocaTcpBaseClient):
    """Fetches product catalog data from moca_service over raw TCP."""

    def fetch_catalog(self) -> dict[str, Any]:
        try:
            menu_options = self.fetch_menu_options()
            allergy = self.fetch_allergy()
            return self._to_legacy_catalog(menu_options, allergy)
        except MocaCatalogClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaCatalogClientError(
                f"moca_service catalog request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def fetch_menu_options(self) -> dict[str, Any]:
        """Fetch menu and option catalog data from moca_service."""

        try:
            _, payload = self.request(
                CMD_MENU,
                METHOD_GET,
                b"",
            )
            return self._decode_catalog_response(payload, CMD_MENU)
        except MocaCatalogClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaCatalogClientError(
                f"moca_service menu option request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def fetch_allergy(self) -> dict[str, Any]:
        """Fetch allergy catalog data from moca_service."""

        try:
            _, payload = self.request(
                CMD_ALLERGY,
                METHOD_GET,
                b"",
            )
            return self._decode_catalog_response(payload, CMD_ALLERGY)
        except MocaCatalogClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaCatalogClientError(
                f"moca_service allergy request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def _decode_catalog_response(self, payload: bytes, catalog_type: int) -> dict[str, Any]:
        catalog = decode_catalog_payload(payload, catalog_type)
        if "error" in catalog:
            message = catalog.get("message", catalog.get("error", "catalog error"))
            raise MocaCatalogClientError(str(message))
        return catalog

    def _to_legacy_catalog(self, menu_options: dict[str, Any], allergy: dict[str, Any]) -> dict[str, Any]:
        menu = []
        surcharges: dict[str, int] = {}
        for item in menu_options.get("menu", []):
            options = item.get("options", [])
            groups = {
                str(option.get("option_group", "")): True
                for option in options
                if isinstance(option, dict)
            }
            option_names_by_group: dict[str, set[str]] = {}
            for option in options:
                if not isinstance(option, dict):
                    continue
                group = str(option.get("option_group", ""))
                name = str(option.get("option_name", ""))
                option_names_by_group.setdefault(group, set()).add(name)
                price = int(option.get("price", 0))
                if price > 0:
                    surcharges[f"{self._legacy_option_key(group)}:{name}"] = price

            menu.append(
                {
                    "id": int(item["id"]),
                    "name": str(item.get("name", "")),
                    "emoji": str(item.get("image", "")),
                    "price": int(item["price"]),
                    "hot": "HOT" in option_names_by_group.get("온도", set()),
                    "ice": "ICE" in option_names_by_group.get("온도", set()),
                    "shot": "에스프레소 샷" in groups,
                    "milk": "우유" in groups,
                }
            )
        return {"menu": menu, "allergy": allergy.get("allergy", []), "surcharges": surcharges}

    def _legacy_option_key(self, group_name: str) -> str:
        return {
            "에스프레소 샷": "shot",
            "우유": "milk",
            "온도": "temperature",
        }.get(group_name, group_name)


class MocaTcpOrderClient(MocaTcpBaseClient):
    """Creates orders in moca_service using the MOCA raw TCP order payload."""

    def create_order(self, items: list[MocaOrderItem]) -> int:
        payload = self.encode_order_request(items)
        try:
            _, response_payload = self.request(CMD_ORDER, METHOD_SET, payload)
            return self._decode_order_response(response_payload)
        except MocaOrderRejected:
            raise
        except MocaOrderClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaOrderClientError(
                f"moca_service order request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def encode_order_request(self, items: list[MocaOrderItem]) -> bytes:
        return encode_order_request_payload(items)

    def _decode_order_response(self, payload: bytes) -> int:
        ok, order_id, message = decode_order_response_payload(payload)
        if not ok:
            raise MocaOrderRejected(message or "order rejected")
        if order_id is None:
            raise MocaOrderClientError("order response missing order_id")
        return order_id


class MocaTcpTableClient(MocaTcpBaseClient):
    """Fetches table assignment state from moca_service over raw TCP."""

    def fetch_tables(self) -> list[dict]:
        try:
            _, payload = self.request(CMD_TABLE, METHOD_GET, b"")
            return self._decode_table_response(payload)
        except MocaTableClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaTableClientError(
                f"moca_service table request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def _decode_table_response(self, payload: bytes) -> list[dict]:
        tables = decode_table_payload(payload)
        if tables and "error" in tables[0]:
            message = tables[0].get("message", tables[0].get("error", "table error"))
            raise MocaTableClientError(str(message))
        return tables

    def assign_table(self, order_id: int, receive_type: ReceiveType, table_id: int | None) -> None:
        payload = encode_table_assignment_request_payload(order_id, receive_type, table_id)
        try:
            _, response_payload = self.request(CMD_TABLE, METHOD_SET, payload)
            self._raise_if_assignment_failed(response_payload)
        except (MocaTableAssignmentNotFound, MocaTableAssignmentRejected):
            raise
        except MocaTableClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaTableClientError(
                f"moca_service table assignment request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def _raise_if_assignment_failed(self, payload: bytes) -> None:
        ok, error_code, message = decode_table_assignment_response_payload(payload)
        if ok:
            return
        if error_code == ERROR_ORDER_NOT_FOUND:
            raise MocaTableAssignmentNotFound(message or "order not found")
        if error_code == ERROR_TABLE_ASSIGNMENT_REJECTED:
            raise MocaTableAssignmentRejected(message or "table assignment rejected")
        raise MocaTableClientError(message or "table assignment failed")


def _parse_received_response_payload(header: MocaHeader, payload: bytes) -> dict[str, Any]:
    try:
        if header.cmd_type in {CMD_MENU, CMD_ALLERGY}:
            return decode_catalog_payload(payload, header.cmd_type)
        if header.cmd_type == CMD_ORDER:
            return _parse_order_response_payload(payload)
        if header.cmd_type == CMD_TABLE and header.method == METHOD_GET:
            return {"tables": decode_table_payload(payload)}
        if header.cmd_type == CMD_TABLE and header.method == METHOD_SET:
            return _parse_table_assignment_response_payload(payload)
        raise ValueError(f"unsupported response payload cmd=0x{header.cmd_type:02X}")
    except Exception as exc:
        return {"parse_error": str(exc), "raw_payload_hex": payload.hex(" ")}


def _parse_order_response_payload(payload: bytes) -> dict[str, Any]:
    if len(payload) == 5 and payload[0] == STATUS_OK:
        ok, order_id, _ = decode_order_response_payload(payload)
        if ok:
            return {"status": "ok", "order_id": order_id}
    if payload[:1] == bytes([STATUS_ERROR]):
        error_code, message = decode_error_payload(payload)
        return {"status": "error", "error_code": error_code, "message": message}
    raise ValueError(f"invalid order response payload length: {len(payload)}")


def _parse_table_assignment_response_payload(payload: bytes) -> dict[str, Any]:
    if payload == bytes([STATUS_OK]):
        return {"status": "ok"}
    error_code, message = decode_error_payload(payload)
    return {"status": "error", "error_code": error_code, "message": message}
