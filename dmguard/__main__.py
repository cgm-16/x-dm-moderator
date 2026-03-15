import uvicorn

from dmguard.app import create_app
from dmguard.config import load_app_config
from dmguard.logging_setup import setup_logging


def main() -> int:
    config = load_app_config()
    setup_logging(config)
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
