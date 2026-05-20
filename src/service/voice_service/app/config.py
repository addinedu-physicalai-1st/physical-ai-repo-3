import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceServiceConfig:
    service_name: str
    http_host: str
    http_port: int


def load_config() -> VoiceServiceConfig:
    return VoiceServiceConfig(
        service_name=os.getenv("VOICE_SERVICE_NAME", "voice_service"),
        http_host=os.getenv("VOICE_SERVICE_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.getenv("VOICE_SERVICE_HTTP_PORT", "8010")),
    )
