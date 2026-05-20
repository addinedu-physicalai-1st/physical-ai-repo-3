from app.config import configure_logging, load_config
from app.services.status_service import StatusService

config = load_config()
logger = configure_logging(config.service_name)
status_service = StatusService(config, logger)
