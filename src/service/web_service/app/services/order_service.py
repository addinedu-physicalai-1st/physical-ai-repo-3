import threading
import uuid

from app.models.order import Order, OrderCreate
from app.models.menu import MenuItem
from app.services import menu_service


_lock = threading.Lock()
_orders: dict[str, Order] = {}
_counter = 41  # 키오스크 원본의 첫 표시값(42)에 맞춤
_moca_order_counter = 1000


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


def reset() -> None:
    global _counter, _moca_order_counter
    with _lock:
        _orders.clear()
        _counter = 41
        _moca_order_counter = 1000


def _calc_total(payload: OrderCreate) -> int:
    total = 0
    catalog = menu_service.fetch_catalog()
    menu = {m.id: m for m in (MenuItem.model_validate(item) for item in catalog.get("menu", []))}
    surcharges = {str(key): int(value) for key, value in catalog.get("surcharges", {}).items()}
    for item in payload.items:
        m = menu.get(item.menu_id)
        if m is None:
            raise UnknownMenu(f"unknown menu_id={item.menu_id}")
        line = m.price * item.qty
        if item.options.shot == "추가":
            line += surcharges.get("shot:추가", 0) * item.qty
        if item.options.milk == "저지방":
            line += surcharges.get("milk:저지방", 0) * item.qty
        total += line
    return total


def create(payload: OrderCreate) -> Order:
    global _counter, _moca_order_counter

    total = _calc_total(payload)

    with _lock:
        _counter += 1
        _moca_order_counter += 1
        order_number = _counter
        moca_order_id = _moca_order_counter
        order_id = uuid.uuid4().hex
        order = Order(
            id=order_id,
            moca_order_id=moca_order_id,
            order_number=order_number,
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
