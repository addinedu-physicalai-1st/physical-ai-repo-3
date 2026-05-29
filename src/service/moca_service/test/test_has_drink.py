"""test_has_drink.py — has_drink 계산 및 HTTP 페이로드 검증.

테스트 대상:
  1. ManufactureOrderItem.product_type 기반 has_drink 계산
     - 음료만 → True
     - 음식만(핫도그 등) → False
     - 음료+음식 혼합 → True
     - 빈 주문 → False

  2. DobyModeServingPort.start_serving() → opserver POST /api/v1/pickup 페이로드 검증
     - has_drink 값이 HTTP body에 정확히 포함되는지

실행:
  cd src/service/moca_service
  python3 -m pytest test/test_has_drink.py -v
"""

import json
import sys
import unittest.mock as mock
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.in_memory.workflow_inmemory_state import ManufactureOrderItem
from app.communication.controller_ports import DobyModeServingPort


# ──────────────── 헬퍼 ────────────────

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


# ──────────────── 1. has_drink 계산 로직 ────────────────

class TestHasDrinkCalculation:
    """DobyModeServingPort 내 has_drink 계산 로직 검증."""

    def _port(self) -> DobyModeServingPort:
        return DobyModeServingPort(
            doby_runtime=MagicMock(),
            logger=MagicMock(),
            opserver_url="http://localhost:8800",
        )

    def _captured_payload(self, order_items: list) -> dict:
        """start_serving 호출 시 전송된 HTTP body를 캡처해 반환."""
        port = self._port()
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data)
            resp = MagicMock()
            resp.read.return_value = b'{"status": "ok"}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("app.communication.controller_ports.urllib.request.urlopen", fake_urlopen):
            port.start_serving(
                command_id="cmd-001",
                order_id=42,
                table_number=1,
                order_items=order_items,
            )

        return captured.get("body", {})

    def test_drink_only_is_true(self):
        payload = self._captured_payload([_drink("아메리카노"), _drink("카페라떼")])
        assert payload["has_drink"] is True

    def test_food_only_is_false(self):
        payload = self._captured_payload([_food("핫도그")])
        assert payload["has_drink"] is False

    def test_snack_only_is_false(self):
        payload = self._captured_payload([_snack("쿠키")])
        assert payload["has_drink"] is False

    def test_drink_and_food_mixed_is_true(self):
        payload = self._captured_payload([_drink("아메리카노"), _food("핫도그")])
        assert payload["has_drink"] is True

    def test_food_and_snack_mixed_is_false(self):
        payload = self._captured_payload([_food("핫도그"), _snack("쿠키")])
        assert payload["has_drink"] is False

    def test_empty_items_is_false(self):
        payload = self._captured_payload([])
        assert payload["has_drink"] is False

    def test_none_items_is_false(self):
        payload = self._captured_payload(None)
        assert payload["has_drink"] is False


# ──────────────── 2. HTTP 페이로드 필드 검증 ────────────────

class TestServingPortPayload:
    """start_serving → POST /api/v1/pickup 페이로드 구조 검증."""

    def _call_and_capture(
        self,
        order_items: list,
        table_number: int = 2,
        command_id: str = "serving:99",
        order_id: int = 99,
    ) -> dict:
        port = DobyModeServingPort(
            doby_runtime=MagicMock(),
            logger=MagicMock(),
            opserver_url="http://testserver:8800",
        )
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data)
            resp = MagicMock()
            resp.read.return_value = b'{"status": "ok"}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("app.communication.controller_ports.urllib.request.urlopen", fake_urlopen):
            result = port.start_serving(command_id, order_id, table_number, order_items)

        assert result is True
        return captured["body"]

    def test_waypoint_formatted_correctly(self):
        body = self._call_and_capture([_drink()], table_number=3)
        assert body["target_table"] == "T03"

    def test_via_pickup_always_true(self):
        body = self._call_and_capture([_drink()])
        assert body["via_pickup"] is True

    def test_event_id_contains_command_id(self):
        body = self._call_and_capture([_drink()], command_id="serving:42")
        assert "serving:42" in body["event_id"]

    def test_order_id_in_body(self):
        body = self._call_and_capture([_drink()], order_id=77)
        assert body["order_id"] == "77"

    def test_has_drink_true_for_drink(self):
        body = self._call_and_capture([_drink("말차라떼")])
        assert body["has_drink"] is True

    def test_has_drink_false_for_food(self):
        body = self._call_and_capture([_food("핫도그")])
        assert body["has_drink"] is False

    def test_invalid_table_returns_false(self):
        port = DobyModeServingPort(
            doby_runtime=MagicMock(),
            logger=MagicMock(),
        )
        result = port.start_serving("cmd", 1, None, [_drink()])
        assert result is False

    def test_zero_table_returns_false(self):
        port = DobyModeServingPort(
            doby_runtime=MagicMock(),
            logger=MagicMock(),
        )
        result = port.start_serving("cmd", 1, 0, [_drink()])
        assert result is False


# ──────────────── 3. HTTP 오류 처리 ────────────────

class TestServingPortErrorHandling:
    """HTTP 실패 시 False 반환 검증."""

    def _port(self):
        return DobyModeServingPort(
            doby_runtime=MagicMock(),
            logger=MagicMock(),
            opserver_url="http://localhost:8800",
        )

    def test_http_error_returns_false(self):
        import urllib.error
        port = self._port()
        with patch(
            "app.communication.controller_ports.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(None, 503, "unavailable", {}, None),
        ):
            result = port.start_serving("cmd", 1, 1, [_drink()])
        assert result is False

    def test_connection_error_returns_false(self):
        port = self._port()
        with patch(
            "app.communication.controller_ports.urllib.request.urlopen",
            side_effect=ConnectionRefusedError("refused"),
        ):
            result = port.start_serving("cmd", 1, 1, [_drink()])
        assert result is False

    def test_opserver_status_not_ok_returns_false(self):
        port = self._port()

        def fake_urlopen(req, timeout=None):
            resp = MagicMock()
            resp.read.return_value = b'{"status": "error", "code": "BUSY"}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("app.communication.controller_ports.urllib.request.urlopen", fake_urlopen):
            result = port.start_serving("cmd", 1, 1, [_drink()])
        assert result is False
