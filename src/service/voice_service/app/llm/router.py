from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.llm.model import LlmModel
from app.llm.prompts import build_system_prompt, build_user_message
from app.schemas import IntentRequest, IntentResponse

router = APIRouter(prefix="/llm", tags=["llm"])


def _get_model(request: Request) -> LlmModel:
    model: Optional[LlmModel] = getattr(request.app.state, "llm_model", None)
    if model is None or not model.loaded:
        raise HTTPException(status_code=503, detail="llm model not loaded")
    return model


def _extract_json(raw: str) -> Optional[dict]:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _names(items: list) -> list[str]:
    names = []
    for it in items or []:
        if isinstance(it, dict):
            name = it.get("name") or it.get("menu_name")
            if isinstance(name, str):
                names.append(name)
        elif isinstance(it, str):
            names.append(it)
    return names


@router.post("/intent", response_model=IntentResponse)
def intent(req: IntentRequest, request: Request) -> IntentResponse:
    model = _get_model(request)
    system_prompt = build_system_prompt(_names(req.menu), _names(req.allergies))
    user_msg = build_user_message(req.user_text, req.current_screen)
    raw, latency_ms = model.generate(system_prompt, user_msg)

    parsed = _extract_json(raw)
    if parsed is None:
        return IntentResponse(
            intent="unknown",
            response_text="다시 말씀해 주세요.",
            latency_ms=latency_ms,
            raw=raw,
        )
    parsed.pop("raw", None)
    parsed.pop("latency_ms", None)
    try:
        resp = IntentResponse(**parsed, latency_ms=latency_ms, raw=raw)
    except ValidationError:
        return IntentResponse(
            intent="unknown",
            response_text="다시 말씀해 주세요.",
            latency_ms=latency_ms,
            raw=raw,
        )

    if resp.intent in {"allergy_select", "allergy_confirm"} and req.current_screen != "screen-allergy":
        return IntentResponse(
            intent="unknown",
            response_text="다시 말씀해 주세요.",
            latency_ms=latency_ms,
            raw=raw,
        )
    return resp
