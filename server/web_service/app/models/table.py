from typing import Literal

from pydantic import BaseModel

TableStatus = Literal["empty", "occupied"]


class Table(BaseModel):
    id: int
    status: TableStatus
