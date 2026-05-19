from typing import Literal

from pydantic import BaseModel, Field

Channel = Literal["kiosk", "table", "voice"]
Delivery = Literal["pickup", "serving"]
Payment = Literal["card", "apple_pay", "samsung_pay"]


class OrderItemOptions(BaseModel):
    shot: str = "기본"
    ice: str = "기본 얼음"
    milk: str = "일반"


class OrderItem(BaseModel):
    menu_id: int
    qty: int = Field(gt=0)
    options: OrderItemOptions = OrderItemOptions()


class OrderCreate(BaseModel):
    channel: Channel
    delivery: Delivery
    # 테이블 음성 주문(channel='table')은 카운터에서 결제하므로 payment 가 비어 있을 수 있음.
    payment: Payment | None = None
    table_no: int | None = None
    items: list[OrderItem] = Field(min_length=1)


class Order(BaseModel):
    id: str
    order_number: int
    channel: Channel
    delivery: Delivery
    payment: Payment | None
    table_no: int | None
    items: list[OrderItem]
    total: int


class OrderCreateResponse(BaseModel):
    order_id: str
    order_number: int
    total: int
