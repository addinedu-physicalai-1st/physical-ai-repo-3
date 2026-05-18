import uvicorn

from app.config import load_config


def main() -> None:
    config = load_config()
    uvicorn.run(
        "app.main:app",
        host=config.http_host,
        port=config.http_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
