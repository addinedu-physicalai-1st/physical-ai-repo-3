from typing import Literal, Optional

from pydantic import BaseModel, Field


Intent = Literal[
    "add_menu",
    "remove_menu",
    "set_option",
    "confirm_order",
    "back",
    "checkout",
    "select_payment",
    "allergy_confirm",
    "allergy_select",
    "cancel_all",
    "unknown",
]

PaymentMethod = Literal["card", "apple_pay", "samsung_pay"]


class TranscribeResponse(BaseModel):
    text: str
    latency_ms: float
    samples: int
    sample_rate: int


class IntentItem(BaseModel):
    menu_name: Optional[str] = None
    qty: int = 1
    options: dict = Field(default_factory=dict)


class IntentRequest(BaseModel):
    user_text: str
    current_screen: Optional[str] = None
    cart: list = Field(default_factory=list)
    menu: list = Field(default_factory=list)
    allergies: list = Field(default_factory=list)


class IntentResponse(BaseModel):
    intent: Intent = "unknown"
    items: list[IntentItem] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    payment_method: Optional[PaymentMethod] = None
    response_text: str = ""
    latency_ms: float = 0.0
    raw: str = ""
