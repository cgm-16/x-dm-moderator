import base64
import hashlib
import hmac
from importlib import metadata
from pathlib import Path
import platform
import tomllib

from fastapi import FastAPI, HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dmguard.config import AppConfig
from dmguard.secrets import FileSecretStore, SecretStore


APP_VERSION = "0.1.0"
MAX_REQUEST_BODY_BYTES = 1_048_576
PACKAGE_NAME = "x-dm-moderator"
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        buffered_messages: list[Message] = []
        consumed_bytes = 0

        while True:
            message = await receive()

            if message["type"] != "http.request":
                buffered_messages.append(message)
                break

            consumed_bytes += len(message.get("body", b""))
            if consumed_bytes > self.max_body_bytes:
                response = JSONResponse(
                    {"detail": "Request body too large"},
                    status_code=413,
                )
                await response(scope, receive, send)
                return

            buffered_messages.append(message)
            if not message.get("more_body", False):
                break

        async def buffered_receive() -> Message:
            if buffered_messages:
                return buffered_messages.pop(0)

            return {"type": "http.disconnect"}

        await self.app(scope, buffered_receive, send)


def build_crc_response_token(crc_token: str, consumer_secret: str) -> str:
    digest = hmac.digest(
        consumer_secret.encode("utf-8"),
        crc_token.encode("utf-8"),
        hashlib.sha256,
    )
    encoded_digest = base64.b64encode(digest).decode("utf-8")
    return f"sha256={encoded_digest}"


def load_app_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        try:
            with PYPROJECT_PATH.open("rb") as fh:
                pyproject = tomllib.load(fh)
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            return APP_VERSION

        project = pyproject.get("project")
        if not isinstance(project, dict):
            return APP_VERSION

        version = project.get("version")
        if not isinstance(version, str) or not version:
            return APP_VERSION

        return version


def build_version_info() -> dict[str, str]:
    return {
        "version": load_app_version(),
        "python": platform.python_version(),
        "fastapi": metadata.version("fastapi"),
        "aiosqlite": metadata.version("aiosqlite"),
        "httpx": metadata.version("httpx"),
    }


def create_app(
    config: AppConfig,
    secret_store: SecretStore | None = None,
) -> FastAPI:
    docs_url = "/docs" if config.debug else None
    redoc_url = "/redoc" if config.debug else None
    openapi_url = "/openapi.json" if config.debug else None
    app_secret_store = secret_store or FileSecretStore()
    version_info = build_version_info()

    app = FastAPI(
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        version=version_info["version"],
    )
    app.state.version_info = version_info
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=MAX_REQUEST_BODY_BYTES,
    )

    @app.get("/webhooks/x")
    async def crc(crc_token: str | None = None) -> dict[str, str]:
        if crc_token is None:
            raise HTTPException(status_code=400, detail="Missing crc_token")

        consumer_secret = app_secret_store.get("x_consumer_secret")
        response_token = build_crc_response_token(crc_token, consumer_secret)
        return {"response_token": response_token}

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/version")
    async def version() -> dict[str, str]:
        return version_info

    return app


__all__ = [
    "APP_VERSION",
    "MAX_REQUEST_BODY_BYTES",
    "build_crc_response_token",
    "create_app",
]
