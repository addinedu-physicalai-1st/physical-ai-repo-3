from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response

from app.tts.model import TtsModel

router = APIRouter(prefix="/tts", tags=["tts"])


def _get_model(request: Request) -> TtsModel:
    model: Optional[TtsModel] = getattr(request.app.state, "tts_model", None)
    if model is None or not model.loaded:
        raise HTTPException(status_code=503, detail="tts model not loaded")
    return model


@router.post("/speak")
def speak(request: Request, text: str = Form(...)) -> Response:
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")
    model = _get_model(request)
    try:
        wav_bytes, sample_rate, latency_ms, duration = model.synthesize(text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"tts failed: {exc}") from exc
    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-Latency-Ms": f"{latency_ms:.1f}",
            "X-Audio-Duration-Sec": f"{duration:.3f}",
            "X-Sample-Rate": str(sample_rate),
        },
    )
