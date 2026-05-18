from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.asr.model import AsrModel
from app.asr.router import router as asr_router
from app.config import load_config
from app.llm.model import LlmModel
from app.llm.router import router as llm_router

config = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.asr_model = None
    app.state.llm_model = None

    asr = AsrModel()
    try:
        asr.load()
        app.state.asr_model = asr
    except Exception as exc:
        print(f"[voice_service] ASR load failed: {exc}")

    llm = LlmModel()
    try:
        llm.load()
        app.state.llm_model = llm
    except Exception as exc:
        print(f"[voice_service] LLM load failed: {exc}")

    yield


app = FastAPI(title="Voice Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(asr_router)
app.include_router(llm_router)


@app.get("/health")
def health() -> dict:
    asr = getattr(app.state, "asr_model", None)
    llm = getattr(app.state, "llm_model", None)
    gpu = "cpu"
    if asr and asr.loaded:
        gpu = asr.gpu
    elif llm and llm.loaded:
        gpu = llm.gpu
    return {
        "status": "ok",
        "service": config.service_name,
        "asr_loaded": bool(asr and asr.loaded),
        "llm_loaded": bool(llm and llm.loaded),
        "tts_loaded": False,
        "gpu": gpu,
    }
