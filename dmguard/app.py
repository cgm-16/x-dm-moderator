from collections.abc import Awaitable, Callable, Sequence
import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hashlib
import hmac
from importlib import metadata
import json
import logging
from pathlib import Path
import platform
import sqlite3
import tomllib

from fastapi import FastAPI, HTTPException, Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dmguard.classifier_backend import build_runtime_classifier_cmd
from dmguard.config import AppConfig
from dmguard.db import get_connection
from dmguard.job_machine import JobStage, JobStatus
from dmguard.moderator import moderate_job
from dmguard.paths import DB_PATH
from dmguard.recovery import recover_stale_jobs
from dmguard.repo_audit import append_audit_row, record_job_error
from dmguard.repo_events import insert_event
from dmguard.repo_jobs import insert_job
from dmguard.repo_kv import kv_get
from dmguard.repo_rejected import insert_rejected_request
from dmguard.schema import bootstrap_schema
from dmguard.secrets import FileSecretStore, SecretStore
from dmguard.webhook_auth import verify_x_signature
from dmguard.worker import worker_loop
from dmguard.x_client import XApiError, XClient


APP_VERSION = "0.1.0"
MAX_REQUEST_BODY_BYTES = 1_048_576
PACKAGE_NAME = "x-dm-moderator"
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"
WEBHOOK_PATH = "/webhooks/x"
_MODERATION_POLICY = "O2_violence_harm_cruelty"


BodyLimitExceededHandler = Callable[[Scope, bytes], Awaitable[None]]


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
        buffered_body = bytearray()

        while True:
            message = await receive()

            if message["type"] != "http.request":
                buffered_messages.append(message)
                break

            body = message.get("body", b"")
            buffered_body.extend(body)
            consumed_bytes += len(body)

            if consumed_bytes > self.max_body_bytes:
                if self.on_limit_exceeded is not None:
                    await self.on_limit_exceeded(scope, bytes(buffered_body))
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


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False

    return value.strip().lower() in {"1", "true"}


def _parse_int(value: str | None) -> int:
    if value is None:
        return 0

    try:
        return int(value)
    except ValueError:
        return 0


async def _count_rows(
    connection,
    query: str,
    params: tuple[object, ...] = (),
) -> int:
    cursor = await connection.execute(query, params)

    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()

    if row is None:
        return 0

    return int(row[0])


def _worker_running(app: FastAPI) -> bool:
    worker_task = getattr(app.state, "worker_task", None)
    return worker_task is not None and not worker_task.done()


async def _build_health_payload(
    app: FastAPI,
    db_path: Path,
) -> dict[str, bool | int | str | None]:
    async with get_connection(db_path) as connection:
        configured = _parse_bool(await kv_get(connection, "system_configured"))
        dropped_jobs_total = _parse_int(await kv_get(connection, "dropped_jobs_total"))
        dropped_jobs_last_24h = _parse_int(
            await kv_get(connection, "dropped_jobs_last_24h")
        )
        last_drop_at = await kv_get(connection, "last_drop_at")
        queued_jobs = await _count_rows(
            connection,
            "SELECT COUNT(*) FROM jobs WHERE status = ?",
            (JobStatus.queued.value,),
        )
        processing_jobs = await _count_rows(
            connection,
            "SELECT COUNT(*) FROM jobs WHERE status = ?",
            (JobStatus.processing.value,),
        )
        error_jobs_last_24h = await _count_rows(
            connection,
            """
            SELECT COUNT(*)
            FROM job_errors
            WHERE created_at >= datetime('now', '-24 hours')
            """,
        )

    ready = _worker_running(app)
    return {
        "ok": True,
        "configured": configured,
        "ready": ready,
        "queued_jobs": queued_jobs,
        "processing_jobs": processing_jobs,
        "error_jobs_last_24h": error_jobs_last_24h,
        "dropped_jobs_total": dropped_jobs_total,
        "dropped_jobs_last_24h": dropped_jobs_last_24h,
        "last_drop_at": last_drop_at or None,
    }


def _health_fallback_payload() -> dict[str, bool | int | str | None]:
    return {
        "ok": True,
        "configured": False,
        "ready": False,
        "queued_jobs": 0,
        "processing_jobs": 0,
        "error_jobs_last_24h": 0,
        "dropped_jobs_total": 0,
        "dropped_jobs_last_24h": 0,
        "last_drop_at": None,
    }


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


def _dispatch_error_message(error: Exception) -> str | None:
    if isinstance(error, XApiError) and error.body:
        return error.body

    message = str(error)
    return message or None


def _dispatch_error_http_status(error: Exception) -> int | None:
    if isinstance(error, XApiError):
        return error.status_code

    return None


def _job_stage(job: dict[str, object]) -> str | None:
    stage = job.get("stage")
    if not isinstance(stage, str) or not stage:
        return None

    return stage


async def _dispatch_moderation(
    job: dict[str, object],
    db_path: Path,
    secret_store: SecretStore,
    classifier_cmd: Sequence[str],
    logger: logging.Logger,
) -> JobStatus:
    job_id = int(job["job_id"])
    event_id = str(job["event_id"])
    sender_id = str(job.get("sender_id") or "")

    try:
        async with XClient(secret_store) as x_client:
            async with get_connection(db_path) as connection:
                result = await moderate_job(job, connection, x_client, classifier_cmd)
                await append_audit_row(
                    connection,
                    job_id=job_id,
                    event_id=event_id,
                    sender_id=sender_id,
                    outcome=result.outcome,
                    policy=_MODERATION_POLICY,
                    category_code=result.category_code,
                    rationale=result.rationale,
                    trigger_frame_index=result.trigger_frame_index,
                    trigger_time_sec=result.trigger_time_sec,
                    block_attempted=result.block_attempted,
                )
                await connection.commit()
    except Exception as error:
        logger.exception(
            "Dispatch moderation failed job_id=%s event_id=%s",
            job_id,
            event_id,
        )
        async with get_connection(db_path) as error_conn:
            await record_job_error(
                error_conn,
                job_id=job_id,
                stage=_job_stage(job),
                attempt=int(job.get("attempt") or 0),
                error_type=type(error).__name__,
                error_message=_dispatch_error_message(error),
                http_status=_dispatch_error_http_status(error),
            )
            await error_conn.commit()
        raise

    if result.outcome == "skipped_allowlist":
        return JobStatus.skipped
    if result.outcome == "error":
        return JobStatus.error

    return JobStatus.done


def create_app(
    config: AppConfig,
    secret_store: SecretStore | None = None,
    db_path: Path | None = None,
    classifier_cmd: Sequence[str] | None = None,
    worker_poll_interval_seconds: float = 5.0,
) -> FastAPI:
    docs_url = "/docs" if config.debug else None
    redoc_url = "/redoc" if config.debug else None
    openapi_url = "/openapi.json" if config.debug else None
    app_secret_store = secret_store or FileSecretStore()
    app_db_path = db_path or DB_PATH
    app_classifier_cmd = classifier_cmd or build_runtime_classifier_cmd(config)
    version_info = build_version_info()
    app_logger = logging.getLogger("dmguard")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with get_connection(app_db_path) as connection:
            await bootstrap_schema(connection)
            await recover_stale_jobs(connection, app_logger)
            await connection.commit()

        async def dispatch_fn(job: dict[str, object]) -> JobStatus:
            return await _dispatch_moderation(
                job,
                app_db_path,
                app_secret_store,
                app_classifier_cmd,
                app_logger,
            )

        task = asyncio.create_task(
            worker_loop(
                app_db_path,
                dispatch_fn,
                poll_interval_seconds=worker_poll_interval_seconds,
                logger=app_logger,
            )
        )
        app.state.worker_task = task

        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            app.state.worker_task = None

    app = FastAPI(
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
        version=version_info["version"],
    )
    app.state.version_info = version_info
    app.state.worker_task = None
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=MAX_REQUEST_BODY_BYTES,
        on_limit_exceeded=lambda scope, raw_body: _persist_oversized_webhook_request(
            app_db_path,
            scope,
            raw_body,
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

        message_create_events = _extract_message_create_events(payload)
        if not message_create_events:
            await _persist_rejected_request(
                app_db_path,
                path=WEBHOOK_PATH,
                reason="unsupported_shape",
                remote_ip=_request_client_host(request),
                body_sha256=_sha256_hex(raw_body),
            )
            return Response(status_code=200)

        for event_id, sender_id, event in message_create_events:
            await _enqueue_event(
                app_db_path,
                event_id=event_id,
                payload_json=json.dumps(event),
                sender_id=sender_id,
            )

        return Response(status_code=200)

    @app.get("/health")
    async def health() -> dict[str, bool | int | str | None]:
        try:
            return await _build_health_payload(app, app_db_path)
        except sqlite3.Error:
            app_logger.warning(
                "Health check failed because the database is unreachable"
            )
            return _health_fallback_payload()

    @app.get("/version")
    async def version() -> dict[str, str]:
        return version_info

    return app


async def _persist_oversized_webhook_request(
    db_path: Path,
    scope: Scope,
    raw_body: bytes,
) -> None:
    path = scope.get("path")
    if path != WEBHOOK_PATH:
        return

    await _ensure_schema(db_path)
    await _persist_rejected_request(
        db_path,
        path=WEBHOOK_PATH,
        reason="oversized",
        remote_ip=_scope_client_host(scope),
        body_sha256=_sha256_hex(raw_body),
    )


__all__ = [
    "APP_VERSION",
    "MAX_REQUEST_BODY_BYTES",
    "build_crc_response_token",
    "create_app",
]
