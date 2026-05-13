from fastapi import APIRouter, HTTPException, status

from app.models.order import Order, OrderCreate, OrderCreateResponse
from app.services import order_repo
from app.services.order_repo import (
    OrderError,
    TableRequired,
    TableUnavailable,
    UnknownMenu,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("", response_model=OrderCreateResponse, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate) -> OrderCreateResponse:
    try:
        order = order_repo.create(payload)
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
    order = order_repo.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order
