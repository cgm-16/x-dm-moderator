import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from importlib import metadata
import json
import logging
from pathlib import Path
import platform
import sqlite3
import threading
import tomllib

from fastapi import Request
from fastapi.testclient import TestClient

from dmguard.app import APP_VERSION, MAX_REQUEST_BODY_BYTES
from dmguard.config import AppConfig
from dmguard.job_machine import JobStatus
from tests.conftest import (
    StubSecretStore,
    bootstrap_database,
    build_signature,
    insert_event_row,
    insert_job_row,
    run,
)


def build_config(*, debug: bool = False) -> AppConfig:
    return AppConfig(
        debug=debug,
        log_level="INFO",
        public_hostname="dmguard.duckdns.org",
        acme_email="ori@example.com",
    )


async def fetch_all_rows(
    db_path: Path,
    query: str,
    params: tuple[object, ...] = (),
) -> list[tuple[object, ...]]:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(query, params)

        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()


async def seed_health_rows(db_path: Path) -> None:
    from dmguard.db import get_connection

    now = datetime.now(timezone.utc)
    queued_at = now.isoformat().replace("+00:00", "Z")
    processing_started_at = (
        (now - timedelta(minutes=5))
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )
    recent_error_at = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    await insert_event_row(db_path, event_id="queued-event")
    await insert_job_row(
        db_path,
        event_id="queued-event",
        next_run_at=queued_at,
    )

    await insert_event_row(db_path, event_id="processing-event")
    processing_job_id = await insert_job_row(
        db_path,
        event_id="processing-event",
        next_run_at=queued_at,
        status=JobStatus.processing,
        attempt=1,
        processing_started_at=processing_started_at,
    )

    async with get_connection(db_path) as connection:
        await connection.execute(
            """
            INSERT INTO job_errors (
              job_id,
              stage,
              attempt,
              error_type,
              error_message,
              created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                processing_job_id,
                "fetch_dm",
                1,
                "RuntimeError",
                "dispatch failed",
                recent_error_at,
            ),
        )
        await connection.executemany(
            """
            INSERT INTO kv_store (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (
                ("system_configured", "true", "2026-03-12T08:30:00Z"),
                ("dropped_jobs_total", "7", "2026-03-12T08:30:00Z"),
                ("dropped_jobs_last_24h", "2", "2026-03-12T08:30:00Z"),
                ("last_drop_at", "2026-03-12T08:25:00Z", "2026-03-12T08:30:00Z"),
            ),
        )
        await connection.commit()


def build_waiting_worker_loop(
    expected_db_path: Path,
    worker_started: threading.Event,
    worker_cancelled: threading.Event,
    calls: list[tuple[str, Path, str]] | None = None,
):
    async def fake_worker_loop(
        db_path_arg: Path,
        dispatch_fn,
        *,
        poll_interval_seconds: float = 5,
        logger: logging.Logger | None = None,
    ) -> None:
        assert db_path_arg == expected_db_path
        assert callable(dispatch_fn)
        assert poll_interval_seconds == 5
        assert logger is not None
        if calls is not None:
            calls.append(("worker", db_path_arg, logger.name))
        worker_started.set()

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    return fake_worker_loop


def build_webhook_client(
    tmp_path: Path,
    *,
    consumer_secret: str = "consumer-secret",
) -> tuple[TestClient, Path]:
    from dmguard.app import create_app

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    app = create_app(
        build_config(),
        StubSecretStore(x_consumer_secret=consumer_secret),
        db_path=db_path,
    )
    return TestClient(app), db_path


def expected_app_version() -> str:
    try:
        return metadata.version("x-dm-moderator")
    except metadata.PackageNotFoundError:
        with (Path(__file__).resolve().parents[1] / "pyproject.toml").open("rb") as fh:
            pyproject = tomllib.load(fh)

        return pyproject["project"]["version"]


def test_create_app_succeeds_without_db() -> None:
    from dmguard.app import create_app

    app = create_app(build_config())

    assert app is not None


def test_create_app_recovers_stale_jobs_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import dmguard.app as app_module

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))

    calls: list[tuple[Path, str]] = []

    async def fake_recover_stale_jobs(connection, logger: logging.Logger) -> int:
        pragma = "pragma database_list"
        rows = await connection.execute_fetchall(pragma)
        calls.append((Path(rows[0][2]), logger.name))
        return 0

    monkeypatch.setattr(app_module, "recover_stale_jobs", fake_recover_stale_jobs)

    app = app_module.create_app(build_config(), db_path=db_path)

    with TestClient(app):
        pass

    assert calls == [(db_path, "dmguard")]


def test_create_app_starts_worker_loop_and_cancels_on_shutdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import dmguard.app as app_module

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))

    calls: list[tuple[str, Path, str]] = []
    worker_started = threading.Event()
    worker_cancelled = threading.Event()

    async def fake_recover_stale_jobs(connection, logger: logging.Logger) -> int:
        pragma = "pragma database_list"
        rows = await connection.execute_fetchall(pragma)
        calls.append(("recover", Path(rows[0][2]), logger.name))
        return 0

    monkeypatch.setattr(app_module, "recover_stale_jobs", fake_recover_stale_jobs)
    monkeypatch.setattr(
        app_module,
        "worker_loop",
        build_waiting_worker_loop(db_path, worker_started, worker_cancelled, calls),
    )

    app = app_module.create_app(build_config(), db_path=db_path)

    with TestClient(app):
        assert worker_started.wait(timeout=1)

    assert worker_cancelled.wait(timeout=1)
    assert calls == [
        ("recover", db_path, "dmguard"),
        ("worker", db_path, "dmguard"),
    ]


def test_health_endpoint_returns_aggregated_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import dmguard.app as app_module

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    run(seed_health_rows(db_path))

    worker_started = threading.Event()
    worker_cancelled = threading.Event()

    monkeypatch.setattr(
        app_module,
        "worker_loop",
        build_waiting_worker_loop(db_path, worker_started, worker_cancelled),
    )

    app = app_module.create_app(build_config(), db_path=db_path)

    with TestClient(app) as client:
        assert worker_started.wait(timeout=1)
        response = client.get("/health")

    assert worker_cancelled.wait(timeout=1)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "configured": True,
        "ready": True,
        "queued_jobs": 1,
        "processing_jobs": 1,
        "error_jobs_last_24h": 1,
        "dropped_jobs_total": 7,
        "dropped_jobs_last_24h": 2,
        "last_drop_at": "2026-03-12T08:25:00Z",
    }


def test_health_endpoint_reports_not_ready_when_db_unreachable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import dmguard.app as app_module

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))

    worker_started = threading.Event()
    worker_cancelled = threading.Event()

    @asynccontextmanager
    async def broken_get_connection(_db_path: Path):
        raise sqlite3.OperationalError("database unavailable")
        yield

    monkeypatch.setattr(
        app_module,
        "worker_loop",
        build_waiting_worker_loop(db_path, worker_started, worker_cancelled),
    )

    app = app_module.create_app(build_config(), db_path=db_path)

    with TestClient(app) as client:
        assert worker_started.wait(timeout=1)
        monkeypatch.setattr(app_module, "get_connection", broken_get_connection)
        response = client.get("/health")

    assert worker_cancelled.wait(timeout=1)
    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "configured": False,
        "ready": False,
        "queued_jobs": 0,
        "processing_jobs": 0,
        "error_jobs_last_24h": 0,
        "dropped_jobs_total": 0,
        "dropped_jobs_last_24h": 0,
        "last_drop_at": None,
    }


def test_version_endpoint_returns_version_metadata() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config()))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": expected_app_version(),
        "python": platform.python_version(),
        "fastapi": metadata.version("fastapi"),
        "aiosqlite": metadata.version("aiosqlite"),
        "httpx": metadata.version("httpx"),
    }


def test_dep_version_returns_unknown_for_missing_package() -> None:
    from dmguard.app import _dep_version

    assert _dep_version("no-such-package-xyzzy") == "unknown"


def test_version_endpoint_caches_payload_at_app_creation(monkeypatch) -> None:
    import dmguard.app as app_module

    build_calls = 0
    cached_version_info = {
        "version": APP_VERSION,
        "python": "3.12.12",
        "fastapi": "1.0.0",
        "aiosqlite": "2.0.0",
        "httpx": "3.0.0",
    }

    def fake_build_version_info() -> dict[str, str]:
        nonlocal build_calls

        build_calls += 1
        return cached_version_info

    monkeypatch.setattr(app_module, "build_version_info", fake_build_version_info)

    client = TestClient(app_module.create_app(build_config()))

    first_response = client.get("/version")
    second_response = client.get("/version")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == cached_version_info
    assert second_response.json() == cached_version_info
    assert build_calls == 1


def test_crc_endpoint_returns_expected_response_token() -> None:
    from dmguard.app import create_app

    crc_token = "challenge-token"
    consumer_secret = "consumer-secret"
    client = TestClient(
        create_app(build_config(), StubSecretStore(x_consumer_secret=consumer_secret))
    )

    response = client.get("/webhooks/x", params={"crc_token": crc_token})

    expected_digest = hmac.digest(
        consumer_secret.encode("utf-8"),
        crc_token.encode("utf-8"),
        hashlib.sha256,
    )
    expected_token = base64.b64encode(expected_digest).decode("utf-8")

    assert response.status_code == 200
    assert response.json() == {"response_token": f"sha256={expected_token}"}


def test_crc_endpoint_returns_400_when_crc_token_is_missing() -> None:
    from dmguard.app import create_app

    client = TestClient(
        create_app(build_config(), StubSecretStore(x_consumer_secret="consumer-secret"))
    )

    response = client.get("/webhooks/x")

    assert response.status_code == 400


def test_non_debug_app_hides_docs_and_openapi() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config(debug=False)))

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_debug_app_exposes_docs_and_openapi() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config(debug=True)))

    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_request_body_limit_allows_exactly_one_megabyte() -> None:
    from dmguard.app import create_app

    app = create_app(build_config())

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    client = TestClient(app)

    response = client.post("/echo", content=b"x" * MAX_REQUEST_BODY_BYTES)

    assert response.status_code == 200
    assert response.json() == {"size": MAX_REQUEST_BODY_BYTES}


def test_request_body_limit_rejects_payloads_over_one_megabyte() -> None:
    from dmguard.app import create_app

    app = create_app(build_config())

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    client = TestClient(app)

    response = client.post("/echo", content=b"x" * (MAX_REQUEST_BODY_BYTES + 1))

    assert response.status_code == 413


def test_webhook_post_rejects_bad_signature_and_persists_request(
    tmp_path: Path,
) -> None:
    client, db_path = build_webhook_client(tmp_path)
    raw_body = json.dumps(
        {"events": [{"event_type": "MessageCreate", "id": "event-1"}]}
    ).encode("utf-8")

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={"x-twitter-webhooks-signature": "sha256=bad-signature"},
    )

    rejected_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT remote_ip, path, reason, body_sha256
            FROM rejected_requests
            ORDER BY id ASC
            """,
        )
    )

    assert response.status_code == 403
    assert rejected_rows == [
        (
            "testclient",
            "/webhooks/x",
            "bad_signature",
            hashlib.sha256(raw_body).hexdigest(),
        )
    ]


def test_webhook_post_rejects_oversized_body_and_persists_request(
    tmp_path: Path,
) -> None:
    consumer_secret = "consumer-secret"
    client, db_path = build_webhook_client(tmp_path, consumer_secret=consumer_secret)
    raw_body = b"x" * (MAX_REQUEST_BODY_BYTES + 1)

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
        },
    )

    rejected_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT remote_ip, path, reason, body_sha256
            FROM rejected_requests
            ORDER BY id ASC
            """,
        )
    )

    assert response.status_code == 413
    assert rejected_rows == [
        ("testclient", "/webhooks/x", "oversized", hashlib.sha256(raw_body).hexdigest())
    ]


def test_webhook_post_rejects_invalid_json_and_persists_request(tmp_path: Path) -> None:
    consumer_secret = "consumer-secret"
    client, db_path = build_webhook_client(tmp_path, consumer_secret=consumer_secret)
    raw_body = b'{"events": ['

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
        },
    )

    rejected_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT remote_ip, path, reason, body_sha256
            FROM rejected_requests
            ORDER BY id ASC
            """,
        )
    )

    assert response.status_code == 400
    assert rejected_rows == [
        (
            "testclient",
            "/webhooks/x",
            "invalid_json",
            hashlib.sha256(raw_body).hexdigest(),
        )
    ]


def test_webhook_post_rejects_invalid_utf8_json_and_persists_request(
    tmp_path: Path,
) -> None:
    consumer_secret = "consumer-secret"
    client, db_path = build_webhook_client(tmp_path, consumer_secret=consumer_secret)
    raw_body = b"\x80"

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
        },
    )

    rejected_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT remote_ip, path, reason, body_sha256
            FROM rejected_requests
            ORDER BY id ASC
            """,
        )
    )

    assert response.status_code == 400
    assert rejected_rows == [
        (
            "testclient",
            "/webhooks/x",
            "invalid_json",
            hashlib.sha256(raw_body).hexdigest(),
        )
    ]


def test_webhook_post_bootstraps_schema_before_first_write(tmp_path: Path) -> None:
    from dmguard.app import create_app

    consumer_secret = "consumer-secret"
    db_path = tmp_path / "state.db"
    client = TestClient(
        create_app(
            build_config(),
            StubSecretStore(x_consumer_secret=consumer_secret),
            db_path=db_path,
        )
    )
    payload = {
        "events": [
            {
                "event_type": "MessageCreate",
                "id": "bootstrap-event-1",
                "sender_id": "sender-1",
            }
        ]
    }
    raw_body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
        },
    )

    assert response.status_code == 200
    assert run(fetch_all_rows(db_path, "SELECT event_id FROM webhook_events")) == [
        ("bootstrap-event-1",)
    ]
    assert run(fetch_all_rows(db_path, "SELECT event_id FROM jobs")) == [
        ("bootstrap-event-1",)
    ]


def test_webhook_post_enqueues_legacy_message_create_event(tmp_path: Path) -> None:
    consumer_secret = "consumer-secret"
    client, db_path = build_webhook_client(tmp_path, consumer_secret=consumer_secret)
    payload = {
        "direct_message_events": [
            {
                "type": "message_create",
                "id": "legacy-event-1",
                "message_create": {
                    "sender_id": "sender-1",
                    "message_data": {"text": "hello"},
                },
            }
        ]
    }
    raw_body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
        },
    )

    event_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT event_id, payload_json, sender_id
            FROM webhook_events
            ORDER BY event_id ASC
            """,
        )
    )
    job_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT event_id, status, stage, attempt, sender_id
            FROM jobs
            ORDER BY job_id ASC
            """,
        )
    )

    assert response.status_code == 200
    assert len(event_rows) == 1
    assert event_rows[0][0] == "legacy-event-1"
    assert json.loads(str(event_rows[0][1])) == payload["direct_message_events"][0]
    assert event_rows[0][2] == "sender-1"
    assert job_rows == [
        ("legacy-event-1", "queued", "fetch_dm", 0, "sender-1"),
    ]


def test_webhook_post_enqueues_v2_message_create_event(tmp_path: Path) -> None:
    consumer_secret = "consumer-secret"
    client, db_path = build_webhook_client(tmp_path, consumer_secret=consumer_secret)
    payload = {
        "events": [
            {
                "event_type": "MessageCreate",
                "id": "v2-event-1",
                "sender_id": "sender-2",
                "text": "hello",
            }
        ]
    }
    raw_body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
        },
    )

    event_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT event_id, payload_json, sender_id
            FROM webhook_events
            ORDER BY event_id ASC
            """,
        )
    )
    job_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT event_id, status, stage, attempt, sender_id
            FROM jobs
            ORDER BY job_id ASC
            """,
        )
    )

    assert response.status_code == 200
    assert len(event_rows) == 1
    assert event_rows[0][0] == "v2-event-1"
    assert json.loads(str(event_rows[0][1])) == payload["events"][0]
    assert event_rows[0][2] == "sender-2"
    assert job_rows == [
        ("v2-event-1", "queued", "fetch_dm", 0, "sender-2"),
    ]


def test_webhook_post_skips_duplicate_event_id_without_duplicate_job(
    tmp_path: Path,
) -> None:
    consumer_secret = "consumer-secret"
    client, db_path = build_webhook_client(tmp_path, consumer_secret=consumer_secret)
    payload = {
        "events": [
            {
                "event_type": "MessageCreate",
                "id": "event-1",
                "sender_id": "sender-1",
            }
        ]
    }
    raw_body = json.dumps(payload).encode("utf-8")
    headers = {
        "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
    }

    first_response = client.post("/webhooks/x", content=raw_body, headers=headers)
    second_response = client.post("/webhooks/x", content=raw_body, headers=headers)

    event_count = run(
        fetch_all_rows(
            db_path,
            "SELECT COUNT(*) FROM webhook_events",
        )
    )
    job_count = run(
        fetch_all_rows(
            db_path,
            "SELECT COUNT(*) FROM jobs",
        )
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert event_count == [(1,)]
    assert job_count == [(1,)]


def test_webhook_post_persists_signed_unsupported_payload_shape(
    tmp_path: Path,
) -> None:
    consumer_secret = "consumer-secret"
    client, db_path = build_webhook_client(tmp_path, consumer_secret=consumer_secret)
    raw_body = json.dumps({"events": [{"event_type": "FavoriteCreate"}]}).encode(
        "utf-8"
    )

    response = client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret)
        },
    )

    event_count = run(fetch_all_rows(db_path, "SELECT COUNT(*) FROM webhook_events"))
    job_count = run(fetch_all_rows(db_path, "SELECT COUNT(*) FROM jobs"))
    rejected_rows = run(
        fetch_all_rows(
            db_path,
            """
            SELECT remote_ip, path, reason, body_sha256
            FROM rejected_requests
            ORDER BY id ASC
            """,
        )
    )

    assert response.status_code == 200
    assert event_count == [(0,)]
    assert job_count == [(0,)]
    assert rejected_rows == [
        (
            "testclient",
            "/webhooks/x",
            "unsupported_shape",
            hashlib.sha256(raw_body).hexdigest(),
        )
    ]
