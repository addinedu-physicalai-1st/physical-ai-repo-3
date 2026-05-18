from fastapi import APIRouter, HTTPException, status

from app.models.order import Order, OrderCreate, OrderCreateResponse
from app.services import order_service
from app.services.order_service import (
    OrderError,
    OrderRejected,
    OrderServiceUnavailable,
    TableRequired,
    TableUnavailable,
    UnknownMenu,
)
from app.services.menu_service import MenuServiceUnavailable

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("", response_model=OrderCreateResponse, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate) -> OrderCreateResponse:
    try:
        order = order_service.create(payload)
    except MenuServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OrderServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OrderRejected as e:
        raise HTTPException(status_code=502, detail=str(e))
    except TableUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (TableRequired, UnknownMenu) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OrderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OrderCreateResponse(
        order_id=order.id,
        order_number=order.order_number,
        total=order.total,
    )


@router.get("/{order_id}", response_model=Order)
def get_order(order_id: str) -> Order:
    order = order_service.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order
