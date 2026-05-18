from typing import Any

from app.clients.moca_catalog_client import CatalogClient, MocaCatalogClient, MocaCatalogClientError
from app.config import load_config
from app.models.menu import AllergyInfo, MenuItem

_config = load_config()
_catalog_client: CatalogClient = MocaCatalogClient(
    _config.moca_service_host,
    _config.moca_service_port,
)


class MenuServiceUnavailable(RuntimeError):
    pass


def set_catalog_client(client: CatalogClient) -> None:
    global _catalog_client
    _catalog_client = client


def fetch_catalog() -> dict[str, Any]:
    try:
        return _catalog_client.fetch_catalog()
    except MocaCatalogClientError as exc:
        raise MenuServiceUnavailable(str(exc)) from exc


def list_menu() -> list[MenuItem]:
    catalog = fetch_catalog()
    return [MenuItem.model_validate(item) for item in catalog.get("menu", [])]


def get_menu(menu_id: int) -> MenuItem | None:
    return next((m for m in list_menu() if m.id == menu_id), None)


def list_allergy() -> list[AllergyInfo]:
    catalog = fetch_catalog()
    return [AllergyInfo.model_validate(item) for item in catalog.get("allergy", [])]


def get_surcharges() -> dict[str, int]:
    catalog = fetch_catalog()
    return {str(key): int(value) for key, value in catalog.get("surcharges", {}).items()}
