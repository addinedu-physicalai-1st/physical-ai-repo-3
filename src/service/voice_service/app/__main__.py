import os

import uvicorn

from app.config import load_config


def main() -> None:
    config = load_config()
    # 폰 브라우저의 마이크 권한(secure context) 위해 https 종단 필요.
    # 인증서 파일 경로가 환경변수로 주어지면 HTTPS, 없으면 HTTP 그대로 동작.
    ssl_kwargs: dict = {}
    cert = os.getenv("VOICE_SERVICE_SSL_CERT")
    key = os.getenv("VOICE_SERVICE_SSL_KEY")
    if cert and key:
        ssl_kwargs["ssl_certfile"] = cert
        ssl_kwargs["ssl_keyfile"] = key
    uvicorn.run(
        "app.main:app",
        host=config.http_host,
        port=config.http_port,
        log_level="info",
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
