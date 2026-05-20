from app.clients.base_tcp_client import MocaTcpBaseClient
from app.protocol.header_protocol import (
    CMD_TABLE,
    ERROR_ORDER_NOT_FOUND,
    ERROR_TABLE_ASSIGNMENT_REJECTED,
    METHOD_GET,
    METHOD_SET,
)
from app.protocol.table_protocol import (
    ReceiveType,
    decode_table_assignment_response_payload,
    decode_table_payload,
    encode_table_assignment_request_payload,
)


class MocaTableClientError(RuntimeError):
    pass


class MocaTableAssignmentNotFound(MocaTableClientError):
    pass


class MocaTableAssignmentRejected(MocaTableClientError):
    pass


class MocaTcpTableClient(MocaTcpBaseClient):
    """Fetches table assignment state from moca_service over raw TCP."""

    def fetch_tables(self) -> list[dict]:
        try:
            _, payload = self.request(CMD_TABLE, METHOD_GET, b"")
            tables = self._decode_table_response(payload)
            self._logger.info("moca_service table result: %s", tables)
            return tables
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
            self._logger.info(
                "moca_service table assignment result: order_id=%s receive_type=%s table_id=%s status=ok",
                order_id,
                receive_type,
                table_id,
            )
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
