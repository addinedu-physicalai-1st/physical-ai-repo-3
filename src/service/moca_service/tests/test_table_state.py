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
from app.protocol.table_protocol import TableAssignmentRequest


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


def test_moca_service_assigns_dine_in_order_to_table():
    table_assignment_runtime = TableAssignmentRuntime(
        [StoreTableDefinition(7, 7, Decimal("0.000"), Decimal("0.000"))]
    )
    repository = AssignableOrderRepository()
    service = MocaService(
        FakeCatalogRepository(),
        repository,
        table_assignment_runtime,
        NullLogger(),
    )

    service.assign_table(TableAssignmentRequest(1, "dine_in", 7))

    assert repository.assignment.receive_type == "DINE_IN"
    assert repository.assignment.table_number == 7
    assert table_assignment_runtime.list_tables()[0].status == "occupied"


def test_moca_service_assigns_take_out_without_occupying_table():
    table_assignment_runtime = TableAssignmentRuntime(
        [StoreTableDefinition(7, 7, Decimal("0.000"), Decimal("0.000"))]
    )
    repository = AssignableOrderRepository()
    service = MocaService(
        FakeCatalogRepository(),
        repository,
        table_assignment_runtime,
        NullLogger(),
    )

    service.assign_table(TableAssignmentRequest(1, "take_out", 7))

    assert repository.assignment.receive_type == "TAKE_OUT"
    assert repository.assignment.table_number is None
    assert table_assignment_runtime.list_tables()[0].status == "empty"


def test_moca_service_rejects_occupied_table_assignment_without_db_update():
    table_assignment_runtime = TableAssignmentRuntime(
        [StoreTableDefinition(7, 7, Decimal("0.000"), Decimal("0.000"))]
    )
    table_assignment_runtime.occupy_by_table_number(7)
    repository = AssignableOrderRepository()
    service = MocaService(
        FakeCatalogRepository(),
        repository,
        table_assignment_runtime,
        NullLogger(),
    )

    with pytest.raises(Exception):
        service.assign_table(TableAssignmentRequest(1, "dine_in", 7))

    assert repository.assignment.receive_type == "TAKE_OUT"
    assert repository.assignment.table_number is None


class FakeCatalogRepository:
    def fetch_catalog(self):
        return {}


class SuccessfulOrderRepository:
    def create_order(self, request):
        return SimpleNamespace(order_id=1, total_price=1000)


class AssignableOrderRepository(SuccessfulOrderRepository):
    def __init__(self):
        self.assignment = SimpleNamespace(
            order_id=1,
            order_source="COUNTER",
            receive_type="TAKE_OUT",
            table_number=None,
        )

    def fetch_assignment(self, order_id):
        if order_id != self.assignment.order_id:
            return None
        return self.assignment

    def update_assignment(self, order_id, order_source, receive_type, table_number):
        if order_id != self.assignment.order_id:
            return False
        self.assignment = SimpleNamespace(
            order_id=order_id,
            order_source=order_source,
            receive_type=receive_type,
            table_number=table_number,
        )
        return True


class FailingOrderRepository:
    def create_order(self, request):
        raise RuntimeError("db unavailable")


class NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass
