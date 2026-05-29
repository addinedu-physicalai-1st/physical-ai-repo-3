"""schemas.py — pydantic 모델 (REST/WS 페이로드 검증).

API 사양: docs/moca_opserver_api_spec.md §2 (REST), §3 (WebSocket).
"""

from typing import Any
from pydantic import BaseModel, Field


# ---------- 공통 응답 ----------

class ApiResponse(BaseModel):
    """공통 성공 응답 포맷."""
    status: str = "ok"
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = ""


class ApiError(BaseModel):
    """공통 에러 응답 포맷."""
    status: str = "error"
    code: str
    message: str
    ts: str = ""


# ---------- REST 요청 본문 ----------

class OrderItem(BaseModel):
    sku: str
    qty: int = 1
    options: dict[str, Any] = Field(default_factory=dict)


class OrderRequest(BaseModel):
    """POST /api/v1/order — POS 주문 접수."""
    event_id: str
    order_id: str
    customer_id: str = ""
    items: list[OrderItem] = Field(default_factory=list)
    ordered_at: str = ""


class PickupRequest(BaseModel):
    """POST /api/v1/pickup — OpenARM 제조완료."""
    event_id: str
    drink_id: str
    order_id: str = ""
    target_table: str
    via_pickup: bool = True
    has_drink: bool = True
    ready_at: str = ""


class GuideRequest(BaseModel):
    """POST /api/v1/guide — POS 동행 안내 요청."""
    event_id: str
    customer_id: str
    requested_at: str = ""
    preferred_table: str | None = None
    party_size: int = 1


class ModeRequest(BaseModel):
    """POST /api/v1/mode — 운영자 수동 모드 전환."""
    mode: str
    params: dict[str, Any] = Field(default_factory=dict)
    override_priority: bool = False


class CommandRequest(BaseModel):
    """POST /api/v1/command — 운영자 미세 제어."""
    command_type: str          # "utter" | "express" | "skip_table" | "resume"
    payload: dict[str, Any] = Field(default_factory=dict)


class ConfigRequest(BaseModel):
    """POST /api/v1/config — 운영 설정 갱신."""
    patrol_interval_minutes: float | None = None
    patrol_enabled: bool | None = None
    patrol_retrigger_cooldown_sec: float | None = None  # 0 = cooldown 비활성 (테스트용)
    business_hours: str | None = None
    battery_min: float | None = None


# ---------- WebSocket 클라이언트 메시지 ----------

class WsSetMode(BaseModel):
    type: str = "set_mode"
    mode: str
    params: dict[str, Any] = Field(default_factory=dict)
    override_priority: bool = False


class WsEmergencyStop(BaseModel):
    type: str = "emergency_stop"


class WsUtter(BaseModel):
    type: str = "utter"
    text: str
    face_expression: str = ""


class WsSkipTable(BaseModel):
    type: str = "skip_table"
    table_id: str


class WsSetConfig(BaseModel):
    type: str = "set_config"
    patrol_interval_minutes: float | None = None
    patrol_enabled: bool | None = None
    business_hours: str | None = None
    battery_min: float | None = None


class WsAckAlarm(BaseModel):
    type: str = "ack_alarm"
    alarm_code: str
