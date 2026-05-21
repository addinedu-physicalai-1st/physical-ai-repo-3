import logging
import socketserver
from collections.abc import Callable

from app.protocol.health_status_protocol import (
    FRAME_SIZE,
    HEALTH_CMD,
    STATUS_CMD,
    STX,
    parse_frame,
)
from app.protocol.header_protocol import (
    CMD_ALLERGY,
    CMD_MENU,
    CMD_ORDER,
    CMD_TABLE,
    HEADER_SIZE as MOCA_HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    decode_header as decode_moca_header,
    encode_frame as encode_moca_frame,
)
from app.protocol.catalog_protocol import (
    CatalogResponse,
    ProductManagementRequest,
    ProductManagementResponse,
    encode_catalog_response_payload,
    encode_product_management_response_payload,
    parse_product_management_payload,
)
from app.protocol.order_protocol import (
    OrderRequest,
    OrderResponse,
    encode_order_response_payload,
    parse_order_payload,
)
from app.protocol.table_protocol import TableResponse, encode_table_response_payload
from app.protocol.table_protocol import (
    TableAssignmentRequest,
    TableAssignmentResponse,
    encode_table_assignment_response_payload,
    parse_table_assignment_payload,
)

HealthHandler = Callable[[int], None]
StatusHandler = Callable[[int, tuple[str, int]], None]
CatalogHandler = Callable[[], CatalogResponse]
ProductManagementHandler = Callable[[ProductManagementRequest], ProductManagementResponse]
OrderHandler = Callable[[OrderRequest], OrderResponse]
TableHandler = Callable[[], TableResponse]
TableAssignmentHandler = Callable[[TableAssignmentRequest], TableAssignmentResponse]


class TcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        host: str,
        port: int,
        on_health: HealthHandler,
        on_status: StatusHandler,
        on_catalog: CatalogHandler,
        on_product_management: ProductManagementHandler,
        on_order: OrderHandler,
        on_table: TableHandler,
        on_table_assignment: TableAssignmentHandler,
        logger: logging.Logger,
        name: str,
    ):
        super().__init__((host, port), TcpRequestHandler)
        self.logger = logger
        self.name = name
        self.on_health = on_health
        self.on_status = on_status
        self.on_catalog = on_catalog
        self.on_product_management = on_product_management
        self.on_order = on_order
        self.on_table = on_table
        self.on_table_assignment = on_table_assignment


class TcpRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: TcpServer = self.server
        peer = self.client_address
        server.logger.info("%s TCP client connected: %s", server.name, peer)

        try:
            while True:
                first = self._read_exact(1)
                if first is None:
                    return

                if first == bytes([STX]):
                    frame_tail = self._read_exact(FRAME_SIZE - 1)
                    if frame_tail is None:
                        return
                    try:
                        cmd, seq = parse_frame(first + frame_tail)
                    except ValueError as exc:
                        server.logger.warning("invalid tcp frame from %s: %s", peer, exc)
                        continue

                    if cmd == HEALTH_CMD:
                        server.logger.info("received HEALTH trigger from %s seq=%s", peer, seq)
                        server.on_health(seq)
                    elif cmd == STATUS_CMD:
                        server.logger.info("received STATUS frame from %s seq=%s", peer, seq)
                        server.on_status(seq, peer)
                    continue

                if first[0] in {CMD_MENU, CMD_ALLERGY, CMD_ORDER, CMD_TABLE}:
                    self._handle_moca_frame(first)
                    continue

                server.logger.warning("invalid tcp prefix from %s: %s", peer, first.hex(" "))
        finally:
            server.logger.info("%s TCP client disconnected: %s", server.name, peer)

    def _handle_moca_frame(self, first: bytes) -> None:
        server: TcpServer = self.server
        header_tail = self._read_exact(MOCA_HEADER_SIZE - 1)
        if header_tail is None:
            return

        try:
            header = decode_moca_header(first + header_tail)
        except ValueError as exc:
            server.logger.warning("invalid moca tcp header from %s: %s", self.client_address, exc)
            return

        if not (
            (header.cmd_type in {CMD_MENU, CMD_ALLERGY} and header.method == METHOD_GET)
            or (header.cmd_type == CMD_MENU and header.method == METHOD_SET)
            or (header.cmd_type == CMD_ORDER and header.method == METHOD_SET)
            or (header.cmd_type == CMD_TABLE and header.method == METHOD_GET)
            or (header.cmd_type == CMD_TABLE and header.method == METHOD_SET)
        ):
            server.logger.warning(
                "unsupported moca tcp method for cmd from %s: cmd=0x%02X method=0x%02X",
                self.client_address,
                header.cmd_type,
                header.method,
            )
            return

        payload_bytes = self._read_exact(header.payload_size)
        if payload_bytes is None:
            return
        server.logger.info(
            "received MOCA payload from %s: %s",
            self.client_address,
            _decode_received_request_payload(header.cmd_type, header.method, payload_bytes),
        )

        if header.cmd_type in {CMD_MENU, CMD_ALLERGY} and header.method == METHOD_GET:
            self._handle_catalog_frame(header.cmd_type, header.sequence, payload_bytes)
            return
        if header.cmd_type == CMD_MENU and header.method == METHOD_SET:
            self._handle_product_management_frame(header.sequence, payload_bytes)
            return
        if header.cmd_type == CMD_ORDER:
            self._handle_order_frame(header.sequence, payload_bytes)
            return
        if header.cmd_type == CMD_TABLE:
            if header.method == METHOD_GET:
                self._handle_table_frame(header.sequence)
            else:
                self._handle_table_assignment_frame(header.sequence, payload_bytes)
            return

        server.logger.warning("unsupported moca tcp cmd from %s: 0x%02X", self.client_address, header.cmd_type)

    def _handle_catalog_frame(self, cmd_type: int, sequence: int, payload: bytes) -> None:
        server: TcpServer = self.server
        try:
            if payload:
                raise ValueError(f"catalog request payload must be empty: {len(payload)}")
            response = server.on_catalog()
            response_payload = encode_catalog_response_payload(response, cmd_type)
        except Exception as exc:
            server.logger.warning("invalid catalog tcp payload from %s: %s", self.client_address, exc)
            response = CatalogResponse.error(0x01, str(exc))
            response_payload = encode_catalog_response_payload(response, cmd_type)
        self.request.sendall(encode_moca_frame(cmd_type, METHOD_GET, sequence, response_payload))

    def _handle_product_management_frame(self, sequence: int, payload: bytes) -> None:
        server: TcpServer = self.server

        try:
            request = parse_product_management_payload(payload)
        except Exception as exc:
            server.logger.warning("invalid product management tcp payload from %s: %s", self.client_address, exc)
            return

        response = server.on_product_management(request)
        response_payload = encode_product_management_response_payload(response)
        self.request.sendall(encode_moca_frame(CMD_MENU, METHOD_SET, sequence, response_payload))

    def _handle_order_frame(self, sequence: int, payload: bytes) -> None:
        server: TcpServer = self.server

        try:
            request = parse_order_payload(payload)
        except Exception as exc:
            server.logger.warning("invalid order tcp payload from %s: %s", self.client_address, exc)
            return

        response = server.on_order(request)
        response_payload = encode_order_response_payload(response)
        self.request.sendall(encode_moca_frame(CMD_ORDER, METHOD_SET, sequence, response_payload))

    def _handle_table_frame(self, sequence: int) -> None:
        server: TcpServer = self.server
        response = server.on_table()
        payload = encode_table_response_payload(response)
        self.request.sendall(encode_moca_frame(CMD_TABLE, METHOD_GET, sequence, payload))

    def _handle_table_assignment_frame(self, sequence: int, payload: bytes) -> None:
        server: TcpServer = self.server

        try:
            request = parse_table_assignment_payload(payload)
        except Exception as exc:
            server.logger.warning("invalid table assignment tcp payload from %s: %s", self.client_address, exc)
            return

        response = server.on_table_assignment(request)
        response_payload = encode_table_assignment_response_payload(response)
        self.request.sendall(encode_moca_frame(CMD_TABLE, METHOD_SET, sequence, response_payload))

    def _read_exact(self, size: int) -> bytes | None:
        server: TcpServer = self.server
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = self.request.recv(size - len(chunks))
            except OSError as exc:
                server.logger.warning("tcp read failed from %s: %s", self.client_address, exc)
                return None
            if not chunk:
                if chunks:
                    server.logger.warning(
                        "partial tcp frame from %s: %s",
                        self.client_address,
                        bytes(chunks).hex(" "),
                    )
                return None
            chunks.extend(chunk)
        return bytes(chunks)


def _decode_received_request_payload(cmd_type: int, method: int, payload: bytes) -> dict:
    try:
        if cmd_type in {CMD_MENU, CMD_ALLERGY} and method == METHOD_GET:
            if payload:
                raise ValueError(f"catalog request payload must be empty: {len(payload)}")
            return {}
        if cmd_type == CMD_MENU and method == METHOD_SET:
            request = parse_product_management_payload(payload)
            decoded: dict = {"action": request.action}
            if request.product_id:
                decoded["product_id"] = request.product_id
            if request.product is not None:
                decoded["product"] = request.product
            if request.action == "list":
                decoded["include_paused"] = request.include_paused
            return decoded
        if cmd_type == CMD_ORDER and method == METHOD_SET:
            request = parse_order_payload(payload)
            return {
                "item_count": len(request.items),
                "items": [
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in request.items
                ],
            }
        if cmd_type == CMD_TABLE and method == METHOD_GET:
            if payload:
                raise ValueError(f"table request payload must be empty: {len(payload)}")
            return {}
        if cmd_type == CMD_TABLE and method == METHOD_SET:
            request = parse_table_assignment_payload(payload)
            return {
                "order_id": request.order_id,
                "receive_type": request.receive_type,
                "table_number": request.table_number,
            }
        raise ValueError(f"unsupported request payload cmd=0x{cmd_type:02X} method=0x{method:02X}")
    except Exception as exc:
        return {"decode_error": str(exc), "raw_payload_hex": payload.hex(" ")}
