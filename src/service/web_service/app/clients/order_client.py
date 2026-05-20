from app.clients.base_tcp_client import MocaTcpBaseClient
from app.protocol.header_protocol import CMD_ORDER, METHOD_SET
from app.protocol.order_protocol import (
    MocaOrderItem,
    decode_order_response_payload,
    encode_order_request_payload,
)


class MocaOrderClientError(RuntimeError):
    pass


class MocaOrderRejected(MocaOrderClientError):
    pass


class MocaTcpOrderClient(MocaTcpBaseClient):
    """Creates orders in moca_service using the MOCA raw TCP order payload."""

    def create_order(self, items: list[MocaOrderItem]) -> int:
        payload = self.encode_order_request(items)
        try:
            _, response_payload = self.request(CMD_ORDER, METHOD_SET, payload)
            order_id = self._decode_order_response(response_payload)
            self._logger.info("moca_service order result: order_id=%s", order_id)
            return order_id
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
