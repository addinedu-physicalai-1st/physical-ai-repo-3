from typing import Literal

from pydantic import BaseModel, Field

TableStatus = Literal["empty", "occupied"]

class Table(BaseModel):
    id: int
    status: TableStatus



ReceiveType = Literal["take_out", "dine_in"]


class TableAssignmentCreate(BaseModel):
    order_id: int = Field(gt=0)
    receive_type: ReceiveType
    table_number: int | None = None


class TableAssignmentRequest(BaseModel):
    order_id: int = Field(gt=0)
    receive_type: ReceiveType
    table_number: int | None = None


class TableAssignmentResponse(BaseModel):
    success: bool = True
