from app.clients.moca_tcp_client import MocaTcpCatalogClient, MocaTcpOrderClient
from app.config import load_config

_config = load_config()
_catalog_client = MocaTcpCatalogClient(_config.moca_service_host, _config.moca_service_port)
_order_client = MocaTcpOrderClient(_config.moca_service_host, _config.moca_service_port)

def get_catalog_client() -> MocaTcpCatalogClient:
    return _catalog_client

def get_order_client() -> MocaTcpOrderClient:
    return _order_client