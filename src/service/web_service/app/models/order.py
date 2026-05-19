from typing import Literal

from pydantic import BaseModel, Field

Channel = Literal["kiosk", "table"]
ReceiveType = Literal["dine_in", "take_out"]
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
    receive_type: ReceiveType
    payment: Payment
    table_no: int | None = None
    items: list[OrderItem] = Field(min_length=1)


class Order(BaseModel):
    id: str
    moca_order_id: int
    order_number: int
    channel: Channel
    receive_type: ReceiveType
    payment: Payment
    table_no: int | None
    items: list[OrderItem]
    total: int


class OrderCreateResponse(BaseModel):
    order_id: str
    moca_order_id: int
    order_number: int
    total: int
