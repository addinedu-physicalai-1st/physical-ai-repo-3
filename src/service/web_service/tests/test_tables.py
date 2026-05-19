from app.clients.moca_tcp_client import MocaTableClientError
from app.services import table_service


def test_get_tables_returns_4_with_initial_seed(client):
    r = client.get("/api/tables")
    assert r.status_code == 200
    tables = r.json()
    assert len(tables) == 4
    # IDs are 1..4
    assert [t["id"] for t in tables] == [1, 2, 3, 4]
    # Seed: empty, occupied, empty, occupied
    assert [t["status"] for t in tables] == ["empty", "occupied", "empty", "occupied"]


def test_get_tables_returns_503_when_moca_table_request_fails(client):
    class FailingTableClient:
        def fetch_tables(self):
            raise MocaTableClientError("unavailable")

    table_service.set_table_client(FailingTableClient())

    r = client.get("/api/tables")

    assert r.status_code == 503
