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
from app.services import order_service, table_service


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
    table_service.reset()
    order_service.reset()
    yield


@pytest.fixture
def client() -> SimpleASGIClient:
    return SimpleASGIClient()
