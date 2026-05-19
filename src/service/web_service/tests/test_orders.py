from app.clients.moca_tcp_client import MocaOrderClientError, MocaOrderRejected
from app.services import order_service
from tests.conftest import ORDER_CLIENT


def _pickup_payload():
    return {
        "channel": "kiosk",
        "delivery": "pickup",
        "payment": "card",
        "items": [{"menu_id": 1, "qty": 2}],
    }


def _serving_payload(table_no: int):
    return {
        "channel": "table",
        "delivery": "serving",
        "payment": "card",
        "table_no": table_no,
        "items": [{"menu_id": 2, "qty": 1, "options": {"shot": "추가", "ice": "기본 얼음", "milk": "저지방"}}],
    }


def test_post_pickup_order_returns_order_number_and_total(client):
    r = client.post("/api/orders", json=_pickup_payload())
    assert r.status_code == 201
    body = r.json()
    assert "order_id" in body
    assert body["moca_order_id"] == 1001
    assert isinstance(body["order_number"], int)
    assert body["order_number"] >= 42
    # 아메리카노 3500 * 2 = 7000
    assert body["total"] == 7000
    assert len(ORDER_CLIENT.requests) == 1
    items = ORDER_CLIENT.requests[0]
    assert [(item.product_id, item.quantity) for item in items] == [(1, 2)]


def test_post_serving_order_does_not_assign_table(client):
    r = client.post("/api/orders", json=_serving_payload(1))
    assert r.status_code == 201
    tables = client.get("/api/tables").json()
    assert tables[0]["status"] == "empty"
    items = ORDER_CLIENT.requests[0]
    assert [(item.product_id, item.quantity) for item in items] == [(2, 1)]


def test_post_serving_to_occupied_table_creates_order_without_assignment(client):
    r = client.post("/api/orders", json=_serving_payload(2))
    assert r.status_code == 201


def test_post_serving_without_table_no_creates_order(client):
    payload = _serving_payload(1)
    payload.pop("table_no")
    r = client.post("/api/orders", json=payload)
    assert r.status_code == 201


def test_get_order_by_id(client):
    created = client.post("/api/orders", json=_pickup_payload()).json()
    r = client.get(f"/api/orders/{created['order_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == created["order_id"]
    assert body["moca_order_id"] == created["moca_order_id"]
    assert body["delivery"] == "pickup"
    assert body["total"] == 7000


def test_get_unknown_order_returns_404(client):
    r = client.get("/api/orders/does-not-exist")
    assert r.status_code == 404


def test_total_includes_shot_and_lowfat_surcharges(client):
    r = client.post("/api/orders", json=_serving_payload(1))
    body = r.json()
    # 카페라떼 4500 + 샷 추가 500 + 저지방 300 = 5300
    assert body["total"] == 5300


def test_unknown_menu_returns_400(client):
    payload = _pickup_payload()
    payload["items"] = [{"menu_id": 9999, "qty": 1}]
    r = client.post("/api/orders", json=payload)
    assert r.status_code == 400


def test_moca_order_rejection_returns_502(client):
    class RejectingOrderClient:
        def create_order(self, items):
            raise MocaOrderRejected("rejected")

    order_service.set_order_client(RejectingOrderClient())

    r = client.post("/api/orders", json=_pickup_payload())

    assert r.status_code == 502


def test_moca_order_unavailable_returns_503(client):
    class FailingOrderClient:
        def create_order(self, items):
            raise MocaOrderClientError("unavailable")

    order_service.set_order_client(FailingOrderClient())

    r = client.post("/api/orders", json=_pickup_payload())

    assert r.status_code == 503


def test_moca_order_failure_does_not_change_table_assignment(client):
    class FailingOrderClient:
        def create_order(self, items):
            raise MocaOrderClientError("unavailable")

    order_service.set_order_client(FailingOrderClient())

    r = client.post("/api/orders", json=_serving_payload(1))

    assert r.status_code == 503
    tables = client.get("/api/tables").json()
    assert tables[0]["status"] == "empty"
