import threading
from app.models.order import Order, OrderCreate
from app.protocol.order_protocol import MocaOrderItem
from app.clients.moca_shared import get_order_client
from app.clients.order_client import MocaOrderClientError, MocaOrderRejected
from app.services import menu_service


_lock = threading.Lock()
_orders: dict[int, Order] = {}

class OrderError(Exception):
    pass


class TableUnavailable(OrderError):
    pass


class TableRequired(OrderError):
    pass


class UnknownMenu(OrderError):
    pass


class OrderServiceUnavailable(OrderError):
    pass


class OrderRejected(OrderError):
    pass

def _calc_total(payload: OrderCreate) -> int:
    total = 0
    catalog = menu_service.fetch_catalog()
    menu_prices = {item["id"]: item["price"] for item in catalog["menu"]}
    surcharges = catalog["surcharges"]
    for item in payload.items:
        price = menu_prices.get(item.menu_id)
        if price is None:
            raise UnknownMenu(f"unknown menu_id={item.menu_id}")
        line = price * item.qty
        if item.options.shot == "추가":
            line += surcharges.get("shot:추가", 0) * item.qty
        if item.options.milk == "저지방":
            line += surcharges.get("milk:저지방", 0) * item.qty
        total += line
    return total


def create(payload: OrderCreate) -> Order:
    total = _calc_total(payload)
    items = [
        MocaOrderItem(product_id=item.menu_id, quantity=item.qty)
        for item in payload.items
    ]

    try:
        order_id = get_order_client().create_order(items)
    except MocaOrderRejected as exc:
        raise OrderRejected(str(exc)) from exc
    except MocaOrderClientError as exc:
        raise OrderServiceUnavailable(str(exc)) from exc

    with _lock:
        order = Order(
            order_id=order_id,
            order_number=101,
            channel=payload.channel,
            receive_type="pending",
            payment=payload.payment,
            table_no=None,
            items=payload.items,
            total=total,
        )
        _orders[order_id] = order
        return order


def get(order_id: int) -> Order | None:
    with _lock:
        return _orders.get(order_id)
