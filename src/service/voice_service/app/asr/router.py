from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.asr.model import SAMPLE_RATE, AsrModel
from app.schemas import TranscribeResponse

router = APIRouter(prefix="/asr", tags=["asr"])


def _get_model(request: Request) -> AsrModel:
    model: Optional[AsrModel] = getattr(request.app.state, "asr_model", None)
    if model is None or not model.loaded:
        raise HTTPException(status_code=503, detail="asr model not loaded")
    return model


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    context: Optional[str] = Form(default=None),
) -> TranscribeResponse:
    model = _get_model(request)
    wav_bytes = await file.read()
    try:
        text, latency_ms, samples = model.transcribe(wav_bytes, context=context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TranscribeResponse(
        text=text,
        latency_ms=latency_ms,
        samples=samples,
        sample_rate=SAMPLE_RATE,
    )
