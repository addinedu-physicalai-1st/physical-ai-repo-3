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


def _menu_items(items: list) -> list[dict]:
    # 클라이언트 LLM payload 의 menu 객체에서 name + aliases 만 안전하게 추출.
    out: list[dict] = []
    for it in items or []:
        if isinstance(it, dict):
            name = it.get("name") or it.get("menu_name")
            if not isinstance(name, str) or not name:
                continue
            raw_aliases = it.get("aliases") or []
            aliases = [a for a in raw_aliases if isinstance(a, str) and a] if isinstance(raw_aliases, list) else []
            out.append({"name": name, "aliases": aliases})
        elif isinstance(it, str) and it:
            out.append({"name": it, "aliases": []})
    return out


@router.post("/intent", response_model=IntentResponse)
def intent(req: IntentRequest, request: Request) -> IntentResponse:
    model = _get_model(request)
    system_prompt = build_system_prompt(_menu_items(req.menu), _names(req.allergies))
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
