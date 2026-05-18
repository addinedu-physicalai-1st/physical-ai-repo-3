from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_config

config = load_config()

app = FastAPI(title="Voice Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": config.service_name,
        "asr_loaded": False,
        "llm_loaded": False,
        "tts_loaded": False,
        "gpu": False,
    }
