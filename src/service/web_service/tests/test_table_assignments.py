from app.clients.moca_tcp_client import (
    MocaTableAssignmentNotFound,
    MocaTableAssignmentRejected,
    MocaTableClientError,
)
from app.services import table_assignment_service
from tests.conftest import TABLE_CLIENT


def test_post_table_assignment_bridges_to_moca_tcp(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "dine_in", "table_id": 2},
    )

    assert r.status_code == 200
    assert r.json() == {"success": True}
    assert TABLE_CLIENT.assignments == [(1001, "dine_in", 2)]


def test_post_take_out_table_assignment_ignores_table_id(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "take_out", "table_id": 2},
    )

    assert r.status_code == 200
    assert TABLE_CLIENT.assignments == [(1001, "take_out", 2)]


def test_post_dine_in_table_assignment_requires_table_id(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "dine_in"},
    )

    assert r.status_code == 400


def test_post_dine_in_table_assignment_rejects_zero_table_id(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "dine_in", "table_id": 0},
    )

    assert r.status_code == 400


def test_post_table_assignment_maps_not_found_to_404(client):
    class MissingTableClient:
        def assign_table(self, order_id, receive_type, table_id):
            raise MocaTableAssignmentNotFound("order not found")

    table_assignment_service.set_table_client(MissingTableClient())

    r = client.post(
        "/api/table-assignments",
        json={"order_id": 9999, "receive_type": "take_out"},
    )

    assert r.status_code == 404


def test_post_table_assignment_maps_rejected_to_409(client):
    class RejectingTableClient:
        def assign_table(self, order_id, receive_type, table_id):
            raise MocaTableAssignmentRejected("table occupied")

    table_assignment_service.set_table_client(RejectingTableClient())

    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "dine_in", "table_id": 2},
    )

    assert r.status_code == 409


def test_post_table_assignment_maps_unavailable_to_503(client):
    class FailingTableClient:
        def assign_table(self, order_id, receive_type, table_id):
            raise MocaTableClientError("unavailable")

    table_assignment_service.set_table_client(FailingTableClient())

    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "take_out"},
    )

    assert r.status_code == 503
