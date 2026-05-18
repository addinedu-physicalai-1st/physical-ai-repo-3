from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.llm.model import LlmModel
from app.llm.prompts import build_system_prompt
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


def _menu_names(menu: list) -> list[str]:
    names = []
    for m in menu or []:
        if isinstance(m, dict):
            name = m.get("name") or m.get("menu_name")
            if isinstance(name, str):
                names.append(name)
        elif isinstance(m, str):
            names.append(m)
    return names


@router.post("/intent", response_model=IntentResponse)
def intent(req: IntentRequest, request: Request) -> IntentResponse:
    model = _get_model(request)
    system_prompt = build_system_prompt(_menu_names(req.menu))
    raw, latency_ms = model.generate(system_prompt, req.user_text)

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
        return IntentResponse(**parsed, latency_ms=latency_ms, raw=raw)
    except ValidationError:
        return IntentResponse(
            intent="unknown",
            response_text="다시 말씀해 주세요.",
            latency_ms=latency_ms,
            raw=raw,
        )
