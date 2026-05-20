import threading
import uuid

from app.models.order import Order, OrderCreate


_lock = threading.Lock()
_orders: dict[str, Order] = {}

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
    menu_prices = {
        1: 3500,
        2: 4500,
        3: 4500,
        4: 5000,
        5: 5500,
        6: 5500,
        7: 6000,
        8: 7000,
    }
    for item in payload.items:
        price = menu_prices.get(item.menu_id)
        if price is None:
            raise UnknownMenu(f"unknown menu_id={item.menu_id}")
        line = price * item.qty
        if item.options.shot == "추가":
            line += 500 * item.qty
        if item.options.milk == "저지방":
            line += 300 * item.qty
        total += line
    return total


def create(payload: OrderCreate) -> Order:
    total = _calc_total(payload)

    with _lock:
        order_id = uuid.uuid4().hex
        order = Order(
            id=order_id,
            order_number=101,
            channel=payload.channel,
            receive_type=payload.receive_type,
            payment=payload.payment,
            table_no=payload.table_no if payload.receive_type == "dine_in" else None,
            items=payload.items,
            total=total,
        )
        _orders[order_id] = order
        return order


def get(order_id: str) -> Order | None:
    with _lock:
        return _orders.get(order_id)
