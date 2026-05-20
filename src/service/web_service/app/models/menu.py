from pydantic import BaseModel


class MenuItem(BaseModel):
    id: int
    name: str
    aliases: list[str] = []
    emoji: str
    price: int
    hot: bool
    shot: bool
    ice: bool
    milk: bool


class AllergyInfo(BaseModel):
    name: str
    icon: str
    items: list[str]
