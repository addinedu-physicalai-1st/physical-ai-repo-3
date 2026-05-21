import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from app.protocol.catalog_protocol import ProductManagementRequest

if TYPE_CHECKING:
    from app.repository.catalog_repo import (
        AllergyCategoryRepository,
        ProductAllergyRepository,
        ProductOptionGroupRepository,
        ProductRepository,
        ProductRow,
    )


class ProductManagementRejected(Exception):
    pass


class ProductNotFound(Exception):
    pass


@dataclass(frozen=True)
class ProductManagementResult:
    result: dict[str, Any] | None = None
    message: str = ""

    @classmethod
    def ok(cls, result: dict[str, Any]) -> "ProductManagementResult":
        return cls(result=result)

    @classmethod
    def rejected(cls, message: str) -> "ProductManagementResult":
        return cls(message=message)

    @property
    def is_ok(self) -> bool:
        return self.result is not None


class MenuService:
    def __init__(
        self,
        product_repository: "ProductRepository",
        product_option_group_repository: "ProductOptionGroupRepository",
        allergy_category_repository: "AllergyCategoryRepository",
        product_allergy_repository: "ProductAllergyRepository",
        logger: logging.Logger,
    ):
        self.product_repository = product_repository
        self.product_option_group_repository = product_option_group_repository
        self.allergy_category_repository = allergy_category_repository
        self.product_allergy_repository = product_allergy_repository
        self.logger = logger

    def get_catalog(self) -> dict[str, Any]:
        products = self.product_repository.list_by_status("ON_SALE")
        option_groups = self.product_option_group_repository.list_all()
        allergy_categories = self.allergy_category_repository.list_all()
        product_allergies = self.product_allergy_repository.list_all()

        menu = [
            {
                "id": product.product_id,
                "name": product.name,
                "image": product.image_url,
                "price": product.price,
                "options": [],
            }
            for product in products
        ]
        menu_by_id = {item["id"]: item for item in menu}

        surcharges: dict[str, int] = {}
        for option_group in option_groups:
            item = menu_by_id.get(option_group.product_id)
            if item is None:
                continue

            group_name = option_group.name
            catalog_options = _to_catalog_options(group_name, _decode_options(option_group.options))
            item["options"].extend(catalog_options)
            for option in catalog_options:
                if option["price"] > 0:
                    surcharges[f"{_legacy_option_key(group_name)}:{option['option_name']}"] = int(option["price"])

        product_name_by_id = {product.product_id: product.name for product in products}
        allergy_by_id = {
            category.allergy_category_id: {"name": category.name, "icon": category.icon, "items": []}
            for category in allergy_categories
        }
        for product_allergy in product_allergies:
            allergy = allergy_by_id.get(product_allergy.allergy_category_id)
            product_name = product_name_by_id.get(product_allergy.product_id)
            if allergy is not None and product_name is not None:
                allergy["items"].append(product_name)

        return {
            "menu": menu,
            "allergy": list(allergy_by_id.values()),
            "surcharges": surcharges,
        }

    def manage_product(self, request: ProductManagementRequest) -> ProductManagementResult:
        if request.action == "create":
            return self.create_product(request)
        if request.action == "get":
            product = self.product_repository.get(request.product_id)
            if product is None:
                return ProductManagementResult.rejected(f"product {request.product_id} not found")
            return ProductManagementResult.ok({"product": _product_to_dict(product)})
        if request.action == "list":
            return self.list_products(request)
        if request.action == "update":
            return self.update_product(request)
        if request.action == "delete":
            return self.delete_product(request)
        return ProductManagementResult.rejected(f"unsupported product action={request.action}")

    def create_product(self, request: ProductManagementRequest) -> ProductManagementResult:
        product_data, error = _validated_product_create(request.product)
        if error is not None:
            return ProductManagementResult.rejected(error)
        product = self.product_repository.create(product_data)
        return ProductManagementResult.ok({"product": _product_to_dict(product)})

    def update_product(self, request: ProductManagementRequest) -> ProductManagementResult:
        product_data, error = _validated_product_update(request.product)
        if error is not None:
            return ProductManagementResult.rejected(error)
        product = self.product_repository.update(request.product_id, product_data)
        if product is None:
            return ProductManagementResult.rejected(f"product {request.product_id} not found")
        return ProductManagementResult.ok({"product": _product_to_dict(product)})

    def delete_product(self, request: ProductManagementRequest) -> ProductManagementResult:
        deleted = self.product_repository.soft_delete(request.product_id)
        if not deleted:
            return ProductManagementResult.rejected(f"product {request.product_id} not found")
        return ProductManagementResult.ok({"product_id": request.product_id, "deleted": True})

    def list_products(self, request: ProductManagementRequest) -> ProductManagementResult:
        products = self.product_repository.list_products(include_paused=request.include_paused)
        return ProductManagementResult.ok({"products": [_product_to_dict(product) for product in products]})


def _validated_product_create(product: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    if product is None:
        return {}, "product must be an object"
    required = {"name", "description", "image_url", "price", "product_type", "menu_status"}
    missing = sorted(required - set(product))
    if missing:
        return {}, f"missing product field={missing[0]}"
    return _validated_product_update(product, require_non_empty=True)


def _validated_product_update(
    product: dict[str, Any] | None,
    *,
    require_non_empty: bool = False,
) -> tuple[dict[str, Any], str | None]:
    if product is None:
        return {}, "product must be an object"
    allowed = {"name", "description", "image_url", "price", "product_type", "menu_status"}
    unknown = sorted(set(product) - allowed)
    if unknown:
        return {}, f"unknown product field={unknown[0]}"
    if require_non_empty and not product:
        return {}, "product must not be empty"

    validated: dict[str, Any] = {}
    for key in ("name", "description", "image_url"):
        if key in product:
            value = str(product[key]).strip()
            if not value:
                return {}, f"{key} must not be empty"
            validated[key] = value
    if "price" in product:
        price = product["price"]
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            return {}, "price must be a non-negative int"
        validated["price"] = price
    if "product_type" in product:
        product_type = str(product["product_type"])
        if product_type not in {"DRINK", "FOOD", "SNACK"}:
            return {}, f"invalid product_type={product_type}"
        validated["product_type"] = product_type
    if "menu_status" in product:
        menu_status = str(product["menu_status"])
        if menu_status not in {"ON_SALE", "SOLD_OUT", "PAUSED"}:
            return {}, f"invalid menu_status={menu_status}"
        validated["menu_status"] = menu_status
    return validated, None


def _product_to_dict(product: "ProductRow") -> dict[str, Any]:
    return {
        "product_id": product.product_id,
        "name": product.name,
        "description": product.description,
        "image_url": product.image_url,
        "price": product.price,
        "product_type": product.product_type,
        "menu_status": product.menu_status,
    }


def _decode_options(options: Any) -> list[Any]:
    if isinstance(options, list):
        return options
    if isinstance(options, str):
        decoded = json.loads(options)
        return decoded if isinstance(decoded, list) else []
    return []


def _to_catalog_options(group_name: str, options: list[Any]) -> list[dict[str, Any]]:
    default_seen = any(isinstance(option, dict) and bool(option.get("is_default", False)) for option in options)
    catalog_options = []
    for index, option in enumerate(options):
        if isinstance(option, dict):
            option_name = str(option.get("name", ""))
            price = int(option.get("price", 0))
            is_default = bool(option.get("is_default", False)) if default_seen else index == 0
        else:
            option_name = str(option)
            price = 0
            is_default = index == 0 and not default_seen
        catalog_options.append(
            {
                "option_group": group_name,
                "option_name": option_name,
                "price": price,
                "is_default": is_default,
            }
        )
    return catalog_options


def _legacy_option_key(group_name: str) -> str:
    return {
        "에스프레소 샷": "shot",
        "우유": "milk",
        "온도": "temperature",
    }.get(group_name, group_name)
