import threading
import uuid

from app.models.order import Order, OrderCreate
from app.models.menu import MenuItem
from app.services import menu_repo, table_repo

_lock = threading.Lock()
_orders: dict[str, Order] = {}
_counter = 41  # 키오스크 원본의 첫 표시값(42)에 맞춤


class OrderError(Exception):
    pass


class TableUnavailable(OrderError):
    pass


class TableRequired(OrderError):
    pass


class UnknownMenu(OrderError):
    pass


def reset() -> None:
    global _counter
    with _lock:
        _orders.clear()
        _counter = 41


def _calc_total(payload: OrderCreate) -> int:
    total = 0
    catalog = menu_repo.fetch_catalog()
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
    global _counter

    total = _calc_total(payload)

    if payload.delivery == "serving":
        if payload.table_no is None:
            raise TableRequired("table_no is required for serving")
        if not table_repo.occupy(payload.table_no):
            raise TableUnavailable(f"table {payload.table_no} is unavailable")

    with _lock:
        _counter += 1
        order_number = _counter
        order_id = uuid.uuid4().hex
        order = Order(
            id=order_id,
            order_number=order_number,
            channel=payload.channel,
            delivery=payload.delivery,
            payment=payload.payment,
            table_no=payload.table_no if payload.delivery == "serving" else None,
            items=payload.items,
            total=total,
        )
        _orders[order_id] = order
        return order


def get(order_id: str) -> Order | None:
    with _lock:
        return _orders.get(order_id)
