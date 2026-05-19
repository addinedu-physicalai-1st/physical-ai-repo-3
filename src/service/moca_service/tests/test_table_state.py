from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.application.moca_service import MocaService
from app.domain.table_assignment_runtime import (
    StoreTableDefinition,
    TableAssignmentRuntime,
    TableUnavailable,
)
from app.protocol.order_protocol import OrderItemRequest, OrderRequest


def test_table_assignment_runtime_tracks_runtime_assignment():
    runtime = TableAssignmentRuntime(
        [
            StoreTableDefinition(1, 1, Decimal("1.000"), Decimal("2.000")),
            StoreTableDefinition(2, 2, Decimal("3.000"), Decimal("4.000")),
        ]
    )

    runtime.occupy(1)

    tables = runtime.list_tables()
    assert [(table.table_id, table.table_number, table.status) for table in tables] == [
        (1, 1, "occupied"),
        (2, 2, "empty"),
    ]

    with pytest.raises(TableUnavailable):
        runtime.occupy(1)

    runtime.release(1)
    assert [table.status for table in runtime.list_tables()] == ["empty", "empty"]


def test_moca_service_create_order_does_not_assign_table():
    table_assignment_runtime = TableAssignmentRuntime(
        [StoreTableDefinition(7, 7, Decimal("0.000"), Decimal("0.000"))]
    )
    service = MocaService(
        FakeCatalogRepository(),
        SuccessfulOrderRepository(),
        table_assignment_runtime,
        NullLogger(),
    )

    service.create_order(OrderRequest([OrderItemRequest(2, 1)]))

    assert table_assignment_runtime.list_tables()[0].status == "empty"


class FakeCatalogRepository:
    def fetch_catalog(self):
        return {}


class SuccessfulOrderRepository:
    def create_order(self, request):
        return SimpleNamespace(order_id=1, total_price=1000)


class FailingOrderRepository:
    def create_order(self, request):
        raise RuntimeError("db unavailable")


class NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass
