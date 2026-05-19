import pytest
import json
from contextlib import asynccontextmanager
from typing import Any
from fastapi import HTTPException

from app.main import app
from app.models.order import OrderCreate
from app.models.table_assignment import TableAssignmentCreate
from app.routers import menu as menu_router
from app.routers import orders as orders_router
from app.routers import table_assignments as table_assignments_router
from app.routers import tables as tables_router
from app.services import menu_service, order_service, table_assignment_service, table_service


CATALOG = {
    "menu": [
        {"id": 1, "name": "아메리카노", "emoji": "☕", "price": 3500, "hot": True, "shot": True, "ice": True, "milk": False},
        {"id": 2, "name": "카페라떼", "emoji": "☕", "price": 4500, "hot": True, "shot": True, "ice": True, "milk": True},
        {"id": 3, "name": "카푸치노", "emoji": "🫧", "price": 4500, "hot": True, "shot": True, "ice": False, "milk": True},
        {"id": 4, "name": "바닐라라떼", "emoji": "🌼", "price": 5000, "hot": True, "shot": True, "ice": True, "milk": True},
        {"id": 5, "name": "카라멜마키아토", "emoji": "🍮", "price": 5500, "hot": True, "shot": True, "ice": True, "milk": True},
        {"id": 6, "name": "말차라떼", "emoji": "🍵", "price": 5500, "hot": True, "shot": False, "ice": True, "milk": True},
        {"id": 7, "name": "딸기스무디", "emoji": "🍓", "price": 6000, "hot": False, "shot": False, "ice": True, "milk": False},
        {"id": 8, "name": "치즈케이크", "emoji": "🍰", "price": 7000, "hot": False, "shot": False, "ice": False, "milk": False},
    ],
    "allergy": [
        {"name": "유제품", "icon": "🥛", "items": ["카페라떼", "카푸치노", "바닐라라떼", "카라멜마키아토", "말차라떼"]},
        {"name": "글루텐", "icon": "🌾", "items": ["치즈케이크"]},
        {"name": "견과류", "icon": "🥜", "items": ["치즈케이크"]},
        {"name": "계란", "icon": "🥚", "items": ["치즈케이크"]},
        {"name": "대두", "icon": "🌱", "items": ["말차라떼"]},
        {"name": "과일류", "icon": "🍓", "items": ["딸기스무디"]},
    ],
    "surcharges": {"shot:추가": 500, "milk:저지방": 300},
}


class FakeCatalogClient:
    def fetch_catalog(self):
        return CATALOG


class FakeOrderClient:
    def __init__(self):
        self.requests = []
        self.next_order_id = 1001

    def create_order(self, items):
        self.requests.append(items)
        return self.next_order_id


ORDER_CLIENT = FakeOrderClient()


class FakeTableClient:
    def __init__(self):
        self.tables = []
        self.assignments = []

    def fetch_tables(self):
        return self.tables

    def assign_table(self, order_id, receive_type, table_id):
        self.assignments.append((order_id, receive_type, table_id))


TABLE_CLIENT = FakeTableClient()


@asynccontextmanager
async def _test_lifespan(app):
    yield


app.router.lifespan_context = _test_lifespan


class SimpleResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    def json(self):
        return json.loads(self._body.decode("utf-8"))


class SimpleASGIClient:
    def get(self, path: str) -> SimpleResponse:
        try:
            if path == "/api/menu":
                return self._response(200, menu_router.get_menu())
            if path == "/api/allergy":
                return self._response(200, menu_router.get_allergy())
            if path == "/api/tables":
                return self._response(200, tables_router.get_tables())
            if path.startswith("/api/orders/"):
                return self._response(200, orders_router.get_order(path.removeprefix("/api/orders/")))
        except HTTPException as exc:
            return self._response(exc.status_code, {"detail": exc.detail})
        raise AssertionError(f"unsupported test GET path: {path}")

    def post(self, path: str, json: dict[str, Any]) -> SimpleResponse:
        try:
            if path == "/api/orders":
                return self._response(201, orders_router.create_order(OrderCreate.model_validate(json)))
            if path == "/api/table-assignments":
                return self._response(
                    200,
                    table_assignments_router.create_table_assignment(TableAssignmentCreate.model_validate(json)),
                )
        except HTTPException as exc:
            return self._response(exc.status_code, {"detail": exc.detail})
        raise AssertionError(f"unsupported test POST path: {path}")

    def _response(self, status_code: int, content: Any) -> SimpleResponse:
        if hasattr(content, "model_dump"):
            content = content.model_dump()
        elif isinstance(content, list):
            content = [item.model_dump() if hasattr(item, "model_dump") else item for item in content]
        return SimpleResponse(
            status_code,
            json.dumps(content, ensure_ascii=False).encode("utf-8"),
        )


@pytest.fixture(autouse=True)
def reset_state():
    menu_service.set_catalog_client(FakeCatalogClient())
    ORDER_CLIENT.requests.clear()
    ORDER_CLIENT.next_order_id = 1001
    TABLE_CLIENT.tables = [
        {"id": 1, "status": "empty"},
        {"id": 2, "status": "occupied"},
        {"id": 3, "status": "empty"},
        {"id": 4, "status": "occupied"},
    ]
    TABLE_CLIENT.assignments.clear()
    order_service.set_order_client(ORDER_CLIENT)
    table_assignment_service.set_table_client(TABLE_CLIENT)
    table_service.set_table_client(TABLE_CLIENT)
    table_service.reset()
    order_service.reset()
    yield


@pytest.fixture
def client() -> SimpleASGIClient:
    return SimpleASGIClient()
