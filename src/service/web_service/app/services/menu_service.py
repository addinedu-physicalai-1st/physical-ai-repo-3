from typing import Any

from pydantic import ValidationError

from app.models.menu import AllergyInfo, MenuItem
from app.clients.catalog_client import MocaCatalogClientError
from app.clients.moca_shared import get_catalog_client


class MenuServiceUnavailable(RuntimeError):
    pass


class ProductManagementRejected(RuntimeError):
    pass


def manage_product(
    action: str,
    *,
    product_id: int | None = None,
    product: dict[str, Any] | None = None,
    include_paused: bool = False,
) -> dict[str, Any]:
    if action not in {"create", "list", "update", "delete"}:
        raise ProductManagementRejected(f"unsupported product action={action}")
    try:
        return get_catalog_client().manage_product(
            action,
            product_id=product_id,
            product=product,
            include_paused=include_paused,
        )
    except MocaCatalogClientError as exc:
        raise MenuServiceUnavailable(str(exc)) from exc


def create_product(product: dict[str, Any]) -> dict[str, Any]:
    return manage_product("create", product=product)


def list_products(*, include_paused: bool = False) -> dict[str, Any]:
    return manage_product("list", include_paused=include_paused)


def update_product(product_id: int, product: dict[str, Any]) -> dict[str, Any]:
    return manage_product("update", product_id=product_id, product=product)


def delete_product(product_id: int) -> dict[str, Any]:
    return manage_product("delete", product_id=product_id)


def fetch_catalog() -> dict[str, Any]:
    try:
        raw_menu = _fetch_raw_menu()
        menu = [_to_menu_item(item) for item in raw_menu]
        allergy = list_allergy()
        return {
            "menu": [item.model_dump() for item in menu],
            "allergy": [item.model_dump() for item in allergy],
            "surcharges": _get_surcharges_from_raw_menu(raw_menu),
        }
    except MenuServiceUnavailable:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise MenuServiceUnavailable(f"invalid moca_service catalog payload: {exc}") from exc


def list_menu() -> list[MenuItem]:
    try:
        return [_to_menu_item(item) for item in _fetch_raw_menu()]
    except MenuServiceUnavailable:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise MenuServiceUnavailable(f"invalid moca_service menu payload: {exc}") from exc


def _fetch_raw_menu() -> list[dict[str, Any]]:
    try:
        payload = get_catalog_client().fetch_menu_options()
        menu = payload.get("menu", [])
        if not isinstance(menu, list):
            raise MenuServiceUnavailable("moca_service menu payload must be a list")
        return menu
    except MocaCatalogClientError as exc:
        raise MenuServiceUnavailable(str(exc)) from exc
    except (TypeError, ValueError, ValidationError) as exc:
        raise MenuServiceUnavailable(f"invalid moca_service menu payload: {exc}") from exc


def get_menu(menu_id: int) -> MenuItem | None:
    return next((m for m in list_menu() if m.id == menu_id), None)


def list_allergy() -> list[AllergyInfo]:
    try:
        payload = get_catalog_client().fetch_allergy()
        allergy = payload.get("allergy", [])
        if not isinstance(allergy, list):
            raise MenuServiceUnavailable("moca_service allergy payload must be a list")
        return [AllergyInfo.model_validate(item) for item in allergy]
    except MocaCatalogClientError as exc:
        raise MenuServiceUnavailable(str(exc)) from exc
    except (TypeError, ValueError, ValidationError) as exc:
        raise MenuServiceUnavailable(f"invalid moca_service allergy payload: {exc}") from exc


def get_surcharges() -> dict[str, int]:
    try:
        return _get_surcharges_from_raw_menu(_fetch_raw_menu())
    except MenuServiceUnavailable:
        raise
    except (TypeError, ValueError) as exc:
        raise MenuServiceUnavailable(f"invalid moca_service menu payload: {exc}") from exc


def _to_menu_item(item: Any) -> MenuItem:
    if not isinstance(item, dict):
        raise ValueError("menu item must be an object")

    options = item.get("options", [])
    if not isinstance(options, list):
        options = []

    return MenuItem(
        id=item.get("id"),
        name=item.get("name", ""),
        aliases=item.get("aliases", []),
        emoji=item.get("emoji") or item.get("image") or "",
        price=item.get("price"),
        hot=_has_option(options, "temperature", {"hot", "HOT", "핫", "뜨거운", "따뜻한"}),
        shot=_has_group(options, "shot"),
        ice=_has_option(options, "temperature", {"ice", "ICE", "아이스", "차가운"})
        or _has_group(options, "ice"),
        milk=_has_group(options, "milk"),
    )


def _get_surcharges_from_raw_menu(raw_menu: list[dict[str, Any]]) -> dict[str, int]:
    surcharges: dict[str, int] = {}
    for raw_item in raw_menu:
        if not isinstance(raw_item, dict):
            continue
        options = raw_item.get("options", [])
        if not isinstance(options, list):
            continue
        for option in options:
            if not isinstance(option, dict):
                continue
            price = int(option.get("price", 0))
            if price <= 0:
                continue
            key = _legacy_option_key(str(option.get("option_group", "")))
            surcharges[f"{key}:{option.get('option_name', '')}"] = price
    return surcharges


def _has_group(options: list[Any], legacy_key: str) -> bool:
    return any(
        isinstance(option, dict)
        and _legacy_option_key(str(option.get("option_group", ""))) == legacy_key
        for option in options
    )


def _has_option(options: list[Any], legacy_key: str, names: set[str]) -> bool:
    return any(
        isinstance(option, dict)
        and _legacy_option_key(str(option.get("option_group", ""))) == legacy_key
        and str(option.get("option_name", "")) in names
        for option in options
    )


def _legacy_option_key(group_name: str) -> str:
    return {
        "에스프레소 샷": "shot",
        "샷": "shot",
        "얼음": "ice",
        "우유": "milk",
        "온도": "temperature",
    }.get(group_name, group_name)
