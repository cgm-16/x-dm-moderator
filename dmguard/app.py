from collections.abc import Awaitable, Callable
import base64
from datetime import datetime, timezone
import hashlib
import hmac
from importlib import metadata
import json
from pathlib import Path
import platform
import sqlite3
import tomllib

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dmguard.config import AppConfig
from dmguard.db import get_connection
from dmguard.job_machine import JobStage, JobStatus
from dmguard.paths import DB_PATH
from dmguard.repo_events import insert_event
from dmguard.repo_jobs import insert_job
from dmguard.repo_rejected import insert_rejected_request
from dmguard.schema import bootstrap_schema
from dmguard.secrets import FileSecretStore, SecretStore
from dmguard.webhook_auth import verify_x_signature


APP_VERSION = "0.1.0"
MAX_REQUEST_BODY_BYTES = 1_048_576
PACKAGE_NAME = "x-dm-moderator"
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"
WEBHOOK_PATH = "/webhooks/x"


BodyLimitExceededHandler = Callable[[Scope], Awaitable[None]]


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int,
        on_limit_exceeded: BodyLimitExceededHandler | None = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.on_limit_exceeded = on_limit_exceeded

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
                if self.on_limit_exceeded is not None:
                    await self.on_limit_exceeded(scope)
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


def _dep_version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "unknown"


def build_version_info() -> dict[str, str]:
    return {
        "version": load_app_version(),
        "python": platform.python_version(),
        "fastapi": _dep_version("fastapi"),
        "aiosqlite": _dep_version("aiosqlite"),
        "httpx": _dep_version("httpx"),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_hex(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def _scope_client_host(scope: Scope) -> str | None:
    client = scope.get("client")
    if not isinstance(client, tuple) or not client:
        return None

    host = client[0]
    if not isinstance(host, str):
        return None

    return host


def _request_client_host(request: Request) -> str | None:
    if request.client is None:
        return None

    return request.client.host


async def _persist_rejected_request(
    db_path: Path,
    *,
    path: str,
    reason: str,
    remote_ip: str | None,
    body_sha256: str | None = None,
) -> None:
    async with get_connection(db_path) as connection:
        await insert_rejected_request(
            connection,
            received_at=_utc_now(),
            remote_ip=remote_ip,
            path=path,
            reason=reason,
            body_sha256=body_sha256,
        )
        await connection.commit()


async def _ensure_schema(db_path: Path) -> None:
    async with get_connection(db_path) as connection:
        await bootstrap_schema(connection)


def _legacy_message_create_events(
    payload: object,
) -> list[tuple[str, str | None, dict[str, object]]]:
    if not isinstance(payload, dict):
        return []

    raw_events = payload.get("direct_message_events")
    if not isinstance(raw_events, list):
        return []

    extracted_events: list[tuple[str, str | None, dict[str, object]]] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        if raw_event.get("type") != "message_create":
            continue

        event_id = raw_event.get("id")
        message_create = raw_event.get("message_create")
        if not isinstance(event_id, str) or not isinstance(message_create, dict):
            continue

        sender_id = message_create.get("sender_id")
        if sender_id is not None and not isinstance(sender_id, str):
            sender_id = None

        extracted_events.append((event_id, sender_id, raw_event))

    return extracted_events


def _v2_message_create_events(
    payload: object,
) -> list[tuple[str, str | None, dict[str, object]]]:
    if not isinstance(payload, dict):
        return []

    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        return []

    extracted_events: list[tuple[str, str | None, dict[str, object]]] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        if raw_event.get("event_type") != "MessageCreate":
            continue

        event_id = raw_event.get("id")
        sender_id = raw_event.get("sender_id")
        if not isinstance(event_id, str):
            continue
        if sender_id is not None and not isinstance(sender_id, str):
            sender_id = None

        extracted_events.append((event_id, sender_id, raw_event))

    return extracted_events


def _extract_message_create_events(
    payload: object,
) -> list[tuple[str, str | None, dict[str, object]]]:
    return _legacy_message_create_events(payload) + _v2_message_create_events(payload)


async def _enqueue_event(
    db_path: Path,
    *,
    event_id: str,
    payload_json: str,
    sender_id: str | None,
) -> None:
    async with get_connection(db_path) as connection:
        try:
            timestamp = _utc_now()
            await insert_event(
                connection,
                event_id=event_id,
                received_at=timestamp,
                payload_json=payload_json,
                sender_id=sender_id,
            )
            await insert_job(
                connection,
                event_id=event_id,
                status=JobStatus.queued,
                stage=JobStage.fetch_dm,
                next_run_at=timestamp,
                sender_id=sender_id,
            )
            await connection.commit()
        except sqlite3.IntegrityError:
            await connection.rollback()


def create_app(
    config: AppConfig,
    secret_store: SecretStore | None = None,
    db_path: Path | None = None,
) -> FastAPI:
    docs_url = "/docs" if config.debug else None
    redoc_url = "/redoc" if config.debug else None
    openapi_url = "/openapi.json" if config.debug else None
    app_secret_store = secret_store or FileSecretStore()
    app_db_path = db_path or DB_PATH
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
        on_limit_exceeded=lambda scope: _persist_oversized_webhook_request(
            app_db_path,
            scope,
        ),
    )

    @app.get(WEBHOOK_PATH)
    async def crc(crc_token: str | None = None) -> dict[str, str]:
        if crc_token is None:
            raise HTTPException(status_code=400, detail="Missing crc_token")

        consumer_secret = app_secret_store.get("x_consumer_secret")
        response_token = build_crc_response_token(crc_token, consumer_secret)
        return {"response_token": response_token}

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request) -> Response:
        raw_body = await request.body()
        await _ensure_schema(app_db_path)
        consumer_secret = app_secret_store.get("x_consumer_secret")
        signature_header = request.headers.get("x-twitter-webhooks-signature", "")

        if not verify_x_signature(raw_body, signature_header, consumer_secret):
            await _persist_rejected_request(
                app_db_path,
                path=WEBHOOK_PATH,
                reason="bad_signature",
                remote_ip=_request_client_host(request),
                body_sha256=_sha256_hex(raw_body),
            )
            raise HTTPException(status_code=403, detail="Invalid signature")

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await _persist_rejected_request(
                app_db_path,
                path=WEBHOOK_PATH,
                reason="invalid_json",
                remote_ip=_request_client_host(request),
                body_sha256=_sha256_hex(raw_body),
            )
            raise HTTPException(status_code=400, detail="Invalid JSON")

        for event_id, sender_id, event in _extract_message_create_events(payload):
            await _enqueue_event(
                app_db_path,
                event_id=event_id,
                payload_json=json.dumps(event),
                sender_id=sender_id,
            )

        return Response(status_code=200)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/version")
    async def version() -> dict[str, str]:
        return version_info

    return app


async def _persist_oversized_webhook_request(db_path: Path, scope: Scope) -> None:
    path = scope.get("path")
    if path != WEBHOOK_PATH:
        return

    await _ensure_schema(db_path)
    await _persist_rejected_request(
        db_path,
        path=WEBHOOK_PATH,
        reason="oversized",
        remote_ip=_scope_client_host(scope),
    )


__all__ = [
    "APP_VERSION",
    "MAX_REQUEST_BODY_BYTES",
    "build_crc_response_token",
    "create_app",
]
