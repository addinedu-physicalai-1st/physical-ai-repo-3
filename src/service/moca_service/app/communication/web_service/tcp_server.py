import logging
import socketserver
import threading
from typing import Any

from app.communication.web_service.controller import WebServiceTcpController
from app.communication.web_service.protocol.catalog_protocol import (
    CatalogResponse,
    encode_catalog_response_payload,
    encode_product_management_response_payload,
    parse_product_management_payload,
)
from app.communication.web_service.protocol.header_protocol import (
    CMD_ALLERGY,
    CMD_MENU,
    CMD_ORDER,
    CMD_TABLE,
    ERROR_BAD_REQUEST,
    HEADER_SIZE,
    METHOD_GET,
    METHOD_SET,
    MocaHeader,
    decode_header,
    encode_error_payload,
    encode_frame,
)
from app.communication.web_service.protocol.order_protocol import encode_order_response_payload, parse_order_payload
from app.communication.web_service.protocol.table_protocol import (
    encode_table_assignment_response_payload,
    encode_table_response_payload,
    parse_table_assignment_payload,
)


class _ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        controller: WebServiceTcpController,
        logger: logging.Logger,
        name: str,
    ) -> None:
        super().__init__(server_address, _TcpRequestHandler)
        self.controller = controller
        self.logger = logger
        self.name = name


class WebServiceTcpServer:
    def __init__(
        self,
        host: str,
        port: int,
        controller: WebServiceTcpController,
        logger: logging.Logger,
        *,
        name: str = "web_service",
    ) -> None:
        self.host = host
        self.port = port
        self.controller = controller
        self.logger = logger
        self.name = name
        self._server: _ThreadingTcpServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = _ThreadingTcpServer(
            (self.host, self.port),
            self.controller,
            self.logger,
            self.name,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"{self.name}-tcp-server",
        )
        self._thread.start()
        self.logger.info("%s tcp listening on %s", self.name, self._server.server_address)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None

        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def serve_forever(self) -> None:
        with _ThreadingTcpServer((self.host, self.port), self.controller, self.logger, self.name) as server:
            self._server = server
            self.logger.info("%s tcp listening on %s", self.name, server.server_address)
            server.serve_forever()

    def __enter__(self) -> "WebServiceTcpServer":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()


class _TcpRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: _ThreadingTcpServer = self.server
        peer = self.client_address
        server.logger.info("%s tcp client connected: %s", server.name, peer)

        try:
            while True:
                header_bytes = self._read_exact(HEADER_SIZE)
                if header_bytes is None:
                    return

                try:
                    header = decode_header(header_bytes)
                except ValueError as exc:
                    server.logger.warning("invalid moca tcp header from %s: %s", peer, exc)
                    continue

                payload = self._read_exact(header.payload_size)
                if payload is None:
                    return
                self._handle_frame(header, payload)
        finally:
            server.logger.info("%s tcp client disconnected: %s", server.name, peer)

    def _handle_frame(self, header: MocaHeader, payload: bytes) -> None:
        server: _ThreadingTcpServer = self.server
        server.logger.info("received web_service MOCA request: %s", _decode_request_for_log(header, payload))

        if header.cmd_type in {CMD_MENU, CMD_ALLERGY} and header.method == METHOD_GET:
            self._send_catalog(header, payload)
            return
        if header.cmd_type == CMD_MENU and header.method == METHOD_SET:
            self._send_product_management(header, payload)
            return
        if header.cmd_type == CMD_ORDER and header.method == METHOD_SET:
            self._send_order(header, payload)
            return
        if header.cmd_type == CMD_TABLE and header.method == METHOD_GET:
            self._send_table(header, payload)
            return
        if header.cmd_type == CMD_TABLE and header.method == METHOD_SET:
            self._send_table_assignment(header, payload)
            return

        server.logger.warning(
            "unsupported web_service MOCA request from %s: cmd=0x%02X method=0x%02X",
            self.client_address,
            header.cmd_type,
            header.method,
        )
        self._send_error(header, f"unsupported cmd=0x{header.cmd_type:02X} method=0x{header.method:02X}")

    def _send_catalog(self, header: MocaHeader, payload: bytes) -> None:
        server: _ThreadingTcpServer = self.server
        try:
            if payload:
                raise ValueError(f"catalog request payload must be empty: {len(payload)}")
            response = server.controller.get_catalog()
            response_payload = encode_catalog_response_payload(response, header.cmd_type)
        except Exception as exc:
            server.logger.warning("catalog request handling failed from %s: %s", self.client_address, exc)
            response_payload = encode_catalog_response_payload(
                CatalogResponse.error(ERROR_BAD_REQUEST, str(exc)),
                header.cmd_type,
            )
        self._send_response(header, response_payload)

    def _send_product_management(self, header: MocaHeader, payload: bytes) -> None:
        server: _ThreadingTcpServer = self.server
        try:
            request = parse_product_management_payload(payload)
            response = server.controller.manage_product(request)
            response_payload = encode_product_management_response_payload(response)
        except Exception as exc:
            server.logger.warning("product management request handling failed from %s: %s", self.client_address, exc)
            response_payload = encode_error_payload(ERROR_BAD_REQUEST, str(exc))
        self._send_response(header, response_payload)

    def _send_order(self, header: MocaHeader, payload: bytes) -> None:
        server: _ThreadingTcpServer = self.server
        try:
            request = parse_order_payload(payload)
            response = server.controller.create_order(request)
            response_payload = encode_order_response_payload(response)
        except Exception as exc:
            server.logger.warning("order request handling failed from %s: %s", self.client_address, exc)
            response_payload = encode_error_payload(ERROR_BAD_REQUEST, str(exc))
        self._send_response(header, response_payload)

    def _send_table(self, header: MocaHeader, payload: bytes) -> None:
        server: _ThreadingTcpServer = self.server
        try:
            if payload:
                raise ValueError(f"table request payload must be empty: {len(payload)}")
            response = server.controller.get_table_assignment()
            response_payload = encode_table_response_payload(response)
        except Exception as exc:
            server.logger.warning("table request handling failed from %s: %s", self.client_address, exc)
            response_payload = encode_error_payload(ERROR_BAD_REQUEST, str(exc))
        self._send_response(header, response_payload)

    def _send_table_assignment(self, header: MocaHeader, payload: bytes) -> None:
        server: _ThreadingTcpServer = self.server
        try:
            request = parse_table_assignment_payload(payload)
            response = server.controller.determine_receive_type(request)
            response_payload = encode_table_assignment_response_payload(response)
        except Exception as exc:
            server.logger.warning("table assignment request handling failed from %s: %s", self.client_address, exc)
            response_payload = encode_error_payload(ERROR_BAD_REQUEST, str(exc))
        self._send_response(header, response_payload)

    def _send_error(self, header: MocaHeader, message: str) -> None:
        self._send_response(header, encode_error_payload(ERROR_BAD_REQUEST, message))

    def _send_response(self, header: MocaHeader, payload: bytes) -> None:
        self.request.sendall(encode_frame(header.cmd_type, header.method, header.sequence, payload))

    def _read_exact(self, size: int) -> bytes | None:
        server: _ThreadingTcpServer = self.server
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = self.request.recv(size - len(chunks))
            except OSError as exc:
                server.logger.warning("tcp read failed from %s: %s", self.client_address, exc)
                return None
            if not chunk:
                if chunks:
                    server.logger.warning("partial tcp frame from %s: %s", self.client_address, bytes(chunks).hex(" "))
                return None
            chunks.extend(chunk)
        return bytes(chunks)


def _decode_request_for_log(header: MocaHeader, payload: bytes) -> dict[str, Any]:
    try:
        if header.cmd_type in {CMD_MENU, CMD_ALLERGY} and header.method == METHOD_GET:
            if payload:
                raise ValueError(f"catalog request payload must be empty: {len(payload)}")
            return {"cmd": header.cmd_type, "method": header.method, "payload": {}}
        if header.cmd_type == CMD_MENU and header.method == METHOD_SET:
            request = parse_product_management_payload(payload)
            decoded: dict[str, Any] = {"action": request.action}
            if request.product_id:
                decoded["product_id"] = request.product_id
            if request.product is not None:
                decoded["product"] = request.product
            if request.action == "list":
                decoded["include_paused"] = request.include_paused
            return {"cmd": header.cmd_type, "method": header.method, "payload": decoded}
        if header.cmd_type == CMD_ORDER and header.method == METHOD_SET:
            request = parse_order_payload(payload)
            return {
                "cmd": header.cmd_type,
                "method": header.method,
                "payload": {
                    "item_count": len(request.items),
                    "items": [
                        {"product_id": item.product_id, "quantity": item.quantity}
                        for item in request.items
                    ],
                },
            }
        if header.cmd_type == CMD_TABLE and header.method == METHOD_GET:
            if payload:
                raise ValueError(f"table request payload must be empty: {len(payload)}")
            return {"cmd": header.cmd_type, "method": header.method, "payload": {}}
        if header.cmd_type == CMD_TABLE and header.method == METHOD_SET:
            request = parse_table_assignment_payload(payload)
            return {
                "cmd": header.cmd_type,
                "method": header.method,
                "payload": {
                    "order_id": request.order_id,
                    "receive_type": request.receive_type,
                    "table_number": request.table_number,
                },
            }
        raise ValueError(f"unsupported request payload cmd=0x{header.cmd_type:02X} method=0x{header.method:02X}")
    except Exception as exc:
        return {
            "cmd": header.cmd_type,
            "method": header.method,
            "decode_error": str(exc),
            "raw_payload_hex": payload.hex(" "),
        }
