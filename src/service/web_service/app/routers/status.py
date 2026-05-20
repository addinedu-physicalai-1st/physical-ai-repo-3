from typing import Any

from fastapi import APIRouter

from app.dependencies import config, logger, status_service

router = APIRouter(tags=["status"])


@router.get("/health")
def health_check() -> dict[str, str]:
    logger.info("received HTTP /health request")
    return {
        "status": "ok",
        "service": config.service_name,
    }


@router.get("/api/v1/status")
def get_status() -> dict[str, Any]:
    return {
        "service": config.service_name,
        **status_service.status_data(),
    }
