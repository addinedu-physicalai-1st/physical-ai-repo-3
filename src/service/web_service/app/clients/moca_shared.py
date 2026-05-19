from app.clients.moca_tcp_client import MocaTcpCatalogClient, MocaTcpOrderClient, MocaTcpTableClient
from app.config import load_config

_config = load_config()
_catalog_client = MocaTcpCatalogClient(_config.moca_service_host, _config.moca_service_port)
_order_client = MocaTcpOrderClient(_config.moca_service_host, _config.moca_service_port)
_table_client = MocaTcpTableClient(_config.moca_service_host, _config.moca_service_port)

def get_catalog_client() -> MocaTcpCatalogClient:
    return _catalog_client

def get_order_client() -> MocaTcpOrderClient:
    return _order_client

def get_table_client() -> MocaTcpTableClient:
    return _table_client
