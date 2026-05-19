from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.protocol.order_protocol import OrderItemRequest, OrderRequest
from app.service import MocaService
from app.table_state import StoreTableDefinition, TableStateStore, TableUnavailable


def test_table_state_store_tracks_runtime_assignment():
    store = TableStateStore(
        [
            StoreTableDefinition(1, 1, Decimal("1.000"), Decimal("2.000")),
            StoreTableDefinition(2, 2, Decimal("3.000"), Decimal("4.000")),
        ]
    )

    store.occupy(1)

    tables = store.list_tables()
    assert [(table.table_id, table.table_number, table.status) for table in tables] == [
        (1, 1, "occupied"),
        (2, 2, "empty"),
    ]

    with pytest.raises(TableUnavailable):
        store.occupy(1)

    store.release(1)
    assert [table.status for table in store.list_tables()] == ["empty", "empty"]


def test_moca_service_releases_reserved_table_when_order_create_fails():
    table_state_store = TableStateStore(
        [StoreTableDefinition(7, 7, Decimal("0.000"), Decimal("0.000"))]
    )
    service = MocaService(
        [],
        FakeCatalogRepository(),
        FailingOrderRepository(),
        table_state_store,
        NullLogger(),
    )

    with pytest.raises(RuntimeError):
        service.create_order(OrderRequest(1, 7, [OrderItemRequest(2, 1)]))

    assert table_state_store.list_tables()[0].status == "empty"


def test_moca_service_keeps_reserved_table_after_order_create_succeeds():
    table_state_store = TableStateStore(
        [StoreTableDefinition(7, 7, Decimal("0.000"), Decimal("0.000"))]
    )
    service = MocaService(
        [],
        FakeCatalogRepository(),
        SuccessfulOrderRepository(),
        table_state_store,
        NullLogger(),
    )

    service.create_order(OrderRequest(1, 7, [OrderItemRequest(2, 1)]))

    assert table_state_store.list_tables()[0].status == "occupied"


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
