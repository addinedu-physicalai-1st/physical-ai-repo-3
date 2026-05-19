from typing import Literal

from pydantic import BaseModel, Field

ReceiveType = Literal["take_out", "dine_in"]


class TableAssignmentCreate(BaseModel):
    order_id: int = Field(gt=0)
    receive_type: ReceiveType
    table_id: int | None = None


class TableAssignmentResponse(BaseModel):
    success: bool = True
