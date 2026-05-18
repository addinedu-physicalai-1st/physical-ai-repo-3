from app.clients.moca_catalog_client import MocaCatalogClientError
from app.services import menu_repo


class FailingCatalogClient:
    def fetch_catalog(self):
        raise MocaCatalogClientError("catalog unavailable")


def test_get_menu_returns_503_when_catalog_unavailable(client):
    menu_repo.set_catalog_client(FailingCatalogClient())

    r = client.get("/api/menu")

    assert r.status_code == 503


def test_get_allergy_returns_503_when_catalog_unavailable(client):
    menu_repo.set_catalog_client(FailingCatalogClient())

    r = client.get("/api/allergy")

    assert r.status_code == 503


def test_post_order_returns_503_when_catalog_unavailable(client):
    menu_repo.set_catalog_client(FailingCatalogClient())

    r = client.post(
        "/api/orders",
        json={
            "channel": "kiosk",
            "delivery": "pickup",
            "payment": "card",
            "items": [{"menu_id": 1, "qty": 1}],
        },
    )

    assert r.status_code == 503
