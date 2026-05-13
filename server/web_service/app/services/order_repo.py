import threading
import uuid

from app.models.order import Order, OrderCreate
from app.services import menu_repo, table_repo
from app.data.seed import LOWFAT_MILK_SURCHARGE, SHOT_SURCHARGE

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
    for item in payload.items:
        m = menu_repo.get_menu(item.menu_id)
        if m is None:
            raise UnknownMenu(f"unknown menu_id={item.menu_id}")
        line = m.price * item.qty
        if item.options.shot == "추가":
            line += SHOT_SURCHARGE * item.qty
        if item.options.milk == "저지방":
            line += LOWFAT_MILK_SURCHARGE * item.qty
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
