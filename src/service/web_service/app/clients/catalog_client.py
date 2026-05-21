from typing import Any

from app.clients.base_tcp_client import MocaTcpBaseClient
from app.protocol.catalog_protocol import (
    decode_catalog_payload,
    decode_product_management_payload,
    encode_product_management_payload,
)
from app.protocol.header_protocol import CMD_ALLERGY, CMD_MENU, METHOD_GET, METHOD_SET


class MocaCatalogClientError(RuntimeError):
    pass


class MocaTcpCatalogClient(MocaTcpBaseClient):
    """Fetches product catalog data from moca_service over raw TCP."""

    def fetch_menu_options(self) -> dict[str, Any]:
        """Fetch menu and option catalog data from moca_service."""

        try:
            _, payload = self.request(
                CMD_MENU,
                METHOD_GET,
                b"",
            )
            menu_options = decode_catalog_payload(payload, CMD_MENU)
            if "error" in menu_options:
                message = menu_options.get("message", menu_options.get("error", "menu_options error"))
                raise MocaCatalogClientError(str(message))
            self._logger.info("moca_service menu options result: %s", menu_options)
            return menu_options
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaCatalogClientError(
                f"moca_service menu option request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def fetch_allergy(self) -> dict[str, Any]:
        """Fetch allergy catalog data from moca_service."""

        try:
            _, payload = self.request(
                CMD_ALLERGY,
                METHOD_GET,
                b"",
            )
            allergy = decode_catalog_payload(payload, CMD_ALLERGY)
            if "error" in allergy:
                message = allergy.get("message", allergy.get("error", "allergy error"))
                raise MocaCatalogClientError(str(message))
            self._logger.info("moca_service allergy result: %s", allergy)
            return allergy
        except MocaCatalogClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaCatalogClientError(
                f"moca_service allergy request failed: {self.host}:{self.port}: {exc}"
            ) from exc

    def manage_product(
        self,
        action: str,
        *,
        product_id: int | None = None,
        product: dict[str, Any] | None = None,
        include_paused: bool = False,
    ) -> dict[str, Any]:
        """Manage products in moca_service over CMD_MENU SET."""

        try:
            request_payload = encode_product_management_payload(
                action,
                product_id=product_id,
                product=product,
                include_paused=include_paused,
            )
            _, response_payload = self.request(CMD_MENU, METHOD_SET, request_payload)
            result = decode_product_management_payload(response_payload)
            if "error" in result:
                message = result.get("message", result.get("error", "product management error"))
                raise MocaCatalogClientError(str(message))
            self._logger.info("moca_service product management result: %s", result)
            return result
        except MocaCatalogClientError:
            raise
        except (OSError, ValueError) as exc:
            self.close()
            raise MocaCatalogClientError(
                f"moca_service product management request failed: {self.host}:{self.port}: {exc}"
            ) from exc
