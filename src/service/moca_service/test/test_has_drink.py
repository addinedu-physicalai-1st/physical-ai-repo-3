"""Doby serving action port payload tests.

실행:
  cd src/service/moca_service
  PYTHONPATH=. python3 -m pytest test/test_has_drink.py -v
"""

import os
import sys
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.communication.controller_ports import DobyActionServingPort
from app.in_memory.workflow_inmemory_state import ManufactureOrderItem


def _item(product_type: str, name: str = "상품", quantity: int = 1) -> ManufactureOrderItem:
    return ManufactureOrderItem(
        product_id=1,
        product_name=name,
        product_type=product_type,
        selected_options=[],
        quantity=quantity,
        unit_price=1000,
    )


def _drink(name: str = "아메리카노") -> ManufactureOrderItem:
    return _item("DRINK", name)


def _food(name: str = "핫도그") -> ManufactureOrderItem:
    return _item("FOOD", name)


def _snack(name: str = "쿠키") -> ManufactureOrderItem:
    return _item("SNACK", name)


class FakeDobyRuntime:
    serving_action_name = "/serving/execute"

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {"ok": True, "accepted": True}
        self.calls: list[dict[str, Any]] = []

    def request_serving(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def _port(runtime: FakeDobyRuntime | None = None) -> DobyActionServingPort:
    port = DobyActionServingPort(runtime or FakeDobyRuntime(), MagicMock())
    port.set_completion_callback(MagicMock())
    port.set_failure_callback(MagicMock())
    return port


def _captured_call(order_items: list[ManufactureOrderItem] | None) -> dict[str, Any]:
    runtime = FakeDobyRuntime()
    port = _port(runtime)
    ok = port.start_serving(
        command_id="serving:42",
        order_id=42,
        table_number=3,
        order_items=order_items,
    )
    assert ok is True
    assert len(runtime.calls) == 1
    return runtime.calls[0]


def test_drink_only_has_drink_true():
    call = _captured_call([_drink("아메리카노"), _drink("카페라떼")])
    assert call["has_drink"] is True


def test_food_only_has_drink_false():
    call = _captured_call([_food("핫도그")])
    assert call["has_drink"] is False


def test_snack_only_has_drink_false():
    call = _captured_call([_snack("쿠키")])
    assert call["has_drink"] is False


def test_drink_and_food_mixed_has_drink_true():
    call = _captured_call([_drink("아메리카노"), _food("핫도그")])
    assert call["has_drink"] is True


def test_food_and_snack_mixed_has_drink_false():
    call = _captured_call([_food("핫도그"), _snack("쿠키")])
    assert call["has_drink"] is False


def test_empty_items_has_drink_false():
    call = _captured_call([])
    assert call["has_drink"] is False


def test_none_items_has_drink_false():
    call = _captured_call(None)
    assert call["has_drink"] is False


def test_action_goal_payload_shape():
    call = _captured_call([_drink("말차라떼")])
    assert call["command_id"] == "serving:42"
    assert call["order_id"] == 42
    assert call["target_table"] == "T03"
    assert call["drink_id"] == "serving:42"
    assert call["via_pickup"] is True
    assert callable(call["on_completed"])
    assert callable(call["on_failed"])


def test_invalid_table_returns_false_without_runtime_call():
    runtime = FakeDobyRuntime()
    port = _port(runtime)

    assert port.start_serving("serving:1", 1, None, [_drink()]) is False
    assert runtime.calls == []


def test_zero_table_returns_false_without_runtime_call():
    runtime = FakeDobyRuntime()
    port = _port(runtime)

    assert port.start_serving("serving:1", 1, 0, [_drink()]) is False
    assert runtime.calls == []


def test_runtime_rejection_returns_false():
    runtime = FakeDobyRuntime({"ok": False, "code": "ACTION_UNAVAILABLE"})
    port = _port(runtime)

    assert port.start_serving("serving:1", 1, 1, [_drink()]) is False
    assert len(runtime.calls) == 1
