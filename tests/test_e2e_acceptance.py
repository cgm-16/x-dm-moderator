import asyncio
from pathlib import Path
import sys
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from dmguard.config import AppConfig
from dmguard.job_machine import JobStage, JobStatus
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


def create_app_client(
    db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    handler,
    classifier_cmd: list[str],
    worker_poll_interval_seconds: float = 0.01,
    consumer_secret: str = "consumer-secret",
) -> TestClient:
    import dmguard.app as app_module
    import dmguard.classifier_runner as classifier_runner
    import dmguard.media_download as media_download
    from dmguard import x_client as x_client_module

    runtime_tmp_dir = tmp_path / "runtime-tmp"
    transport = httpx.MockTransport(handler)

    monkeypatch.setattr(media_download, "TMP_DIR", runtime_tmp_dir)
    monkeypatch.setattr(classifier_runner, "TMP_DIR", runtime_tmp_dir)
    monkeypatch.setattr(
        app_module,
        "XClient",
        lambda secret_store: x_client_module.XClient(
            secret_store,
            transport=transport,
        ),
    )

    app = app_module.create_app(
        build_config(),
        StubSecretStore(
            x_consumer_secret=consumer_secret,
            x_access_token="access-token",
            x_user_id="bot-user-id",
        ),
        db_path=db_path,
        classifier_cmd=classifier_cmd,
        worker_poll_interval_seconds=worker_poll_interval_seconds,
    )
    return TestClient(app)


async def fetch_one_row(
    db_path: Path,
    query: str,
    params: tuple[object, ...] = (),
) -> tuple[object, ...] | None:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(query, params)

        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()


async def fetch_job(db_path: Path, job_id: int) -> dict[str, object] | None:
    from dmguard.db import get_connection
    from dmguard.repo_jobs import get_job

    async with get_connection(db_path) as connection:
        return await get_job(connection, job_id)


async def find_job_id(db_path: Path, event_id: str) -> int:
    row = await fetch_one_row(
        db_path,
        "SELECT job_id FROM jobs WHERE event_id = ?",
        (event_id,),
    )
    assert row is not None
    return int(row[0])


async def wait_for_job_status(
    db_path: Path,
    job_id: int,
    expected_status: str,
) -> dict[str, object]:
    for _ in range(200):
        job = await fetch_job(db_path, job_id)
        if job is not None and job["status"] == expected_status:
            return job
        await asyncio.sleep(0.01)

    raise AssertionError(f"job {job_id} did not reach status {expected_status}")


def build_webhook_payload(event_id: str, sender_id: str) -> dict[str, object]:
    return {
        "events": [
            {
                "event_type": "MessageCreate",
                "id": event_id,
                "sender_id": sender_id,
            }
        ]
    }


def build_dm_event_response(
    *,
    event_id: str,
    sender_id: str,
    media: list[dict[str, object]] | None = None,
    media_keys: list[str] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "id": event_id,
        "sender_id": sender_id,
        "text": "hello world",
        "created_at": "2026-03-13T00:00:00.000Z",
    }

    payload: dict[str, object] = {"data": data}
    if media_keys:
        data["attachments"] = {"media_keys": media_keys}
    if media:
        payload["includes"] = {"media": media}

    return payload


def post_signed_webhook(
    client: TestClient,
    payload: dict[str, object],
    *,
    consumer_secret: str = "consumer-secret",
):
    raw_body = httpx.Request("POST", "https://example.test", json=payload).content
    return client.post(
        "/webhooks/x",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "x-twitter-webhooks-signature": build_signature(raw_body, consumer_secret),
        },
    )


def safe_classifier_cmd() -> list[str]:
    return [sys.executable, "-m", "dmguard.classifier_fake", "--force-safe"]


def unsafe_classifier_cmd() -> list[str]:
    return [sys.executable, "-m", "dmguard.classifier_fake", "--force-unsafe"]


def test_e2e_safe_media_webhook_adds_sender_to_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        assert request.headers["Authorization"] == "Bearer access-token"

        if request.method == "GET" and request.url.path == "/2/dm_events/event-safe":
            return httpx.Response(
                200,
                json=build_dm_event_response(
                    event_id="event-safe",
                    sender_id="sender-safe",
                    media=[
                        {
                            "media_key": "3_1",
                            "type": "photo",
                            "url": "https://media.example.com/safe-photo.jpg",
                        }
                    ],
                    media_keys=["3_1"],
                ),
            )

        if (
            request.method == "GET"
            and str(request.url) == "https://media.example.com/safe-photo.jpg"
        ):
            return httpx.Response(200, content=b"safe-photo-bytes")

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_app_client(
        db_path,
        tmp_path,
        monkeypatch,
        handler=handler,
        classifier_cmd=safe_classifier_cmd(),
    )

    with client:
        response = post_signed_webhook(
            client,
            build_webhook_payload("event-safe", "sender-safe"),
        )
        assert response.status_code == 200

        job_id = run(find_job_id(db_path, "event-safe"))
        run(wait_for_job_status(db_path, job_id, JobStatus.done.value))

    allowed_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT sender_id, source_event_id
            FROM allowed_senders
            WHERE sender_id = ?
            """,
            ("sender-safe",),
        )
    )
    audit_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT outcome, category_code, block_attempted
            FROM moderation_audit
            WHERE job_id = ?
            """,
            (job_id,),
        )
    )

    assert allowed_row == ("sender-safe", "event-safe")
    assert audit_row == ("safe", "NA: None applying", 0)
    assert requests == [
        (
            "GET",
            "https://api.x.com/2/dm_events/event-safe?event_fields=attachments%2Ccreated_at%2Csender_id%2Ctext&expansions=attachments.media_keys%2Csender_id&media.fields=type%2Curl%2Cpreview_image_url%2Cvariants",
        ),
        ("GET", "https://media.example.com/safe-photo.jpg"),
    ]


def test_e2e_unsafe_media_webhook_blocks_sender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        assert request.headers["Authorization"] == "Bearer access-token"

        if request.method == "GET" and request.url.path == "/2/dm_events/event-unsafe":
            return httpx.Response(
                200,
                json=build_dm_event_response(
                    event_id="event-unsafe",
                    sender_id="sender-unsafe",
                    media=[
                        {
                            "media_key": "3_1",
                            "type": "photo",
                            "url": "https://media.example.com/unsafe-photo.jpg",
                        }
                    ],
                    media_keys=["3_1"],
                ),
            )

        if (
            request.method == "GET"
            and str(request.url) == "https://media.example.com/unsafe-photo.jpg"
        ):
            return httpx.Response(200, content=b"unsafe-photo-bytes")

        if (
            request.method == "POST"
            and request.url.path == "/2/users/bot-user-id/blocking"
        ):
            return httpx.Response(200, json={"data": {"blocking": True}})

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_app_client(
        db_path,
        tmp_path,
        monkeypatch,
        handler=handler,
        classifier_cmd=unsafe_classifier_cmd(),
    )

    with client:
        response = post_signed_webhook(
            client,
            build_webhook_payload("event-unsafe", "sender-unsafe"),
        )
        assert response.status_code == 200

        job_id = run(find_job_id(db_path, "event-unsafe"))
        run(wait_for_job_status(db_path, job_id, JobStatus.done.value))

    blocked_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT sender_id, source_event_id
            FROM blocked_senders
            WHERE sender_id = ?
            """,
            ("sender-unsafe",),
        )
    )
    audit_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT outcome, category_code, block_attempted
            FROM moderation_audit
            WHERE job_id = ?
            """,
            (job_id,),
        )
    )

    assert blocked_row == ("sender-unsafe", "event-unsafe")
    assert audit_row == ("blocked", "O2: Violence, Harm, or Cruelty", 1)
    assert requests[-1] == ("POST", "https://api.x.com/2/users/bot-user-id/blocking")


def test_e2e_block_api_failure_records_error_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        assert request.headers["Authorization"] == "Bearer access-token"

        if request.method == "GET" and request.url.path == "/2/dm_events/event-bfail":
            return httpx.Response(
                200,
                json=build_dm_event_response(
                    event_id="event-bfail",
                    sender_id="sender-bfail",
                    media=[
                        {
                            "media_key": "3_1",
                            "type": "photo",
                            "url": "https://media.example.com/bfail-photo.jpg",
                        }
                    ],
                    media_keys=["3_1"],
                ),
            )

        if (
            request.method == "GET"
            and str(request.url) == "https://media.example.com/bfail-photo.jpg"
        ):
            return httpx.Response(200, content=b"bfail-photo-bytes")

        if (
            request.method == "POST"
            and request.url.path == "/2/users/bot-user-id/blocking"
        ):
            return httpx.Response(500, text="Internal Server Error")

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_app_client(
        db_path,
        tmp_path,
        monkeypatch,
        handler=handler,
        classifier_cmd=unsafe_classifier_cmd(),
    )

    with client:
        response = post_signed_webhook(
            client,
            build_webhook_payload("event-bfail", "sender-bfail"),
        )
        assert response.status_code == 200

        job_id = run(find_job_id(db_path, "event-bfail"))
        run(wait_for_job_status(db_path, job_id, JobStatus.error.value))

    blocked_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT sender_id
            FROM blocked_senders
            WHERE sender_id = ?
            """,
            ("sender-bfail",),
        )
    )
    failed_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT sender_id
            FROM block_failed_senders
            WHERE sender_id = ?
            """,
            ("sender-bfail",),
        )
    )
    audit_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT outcome, category_code, block_attempted
            FROM moderation_audit
            WHERE job_id = ?
            """,
            (job_id,),
        )
    )

    assert blocked_row is None
    assert failed_row is not None
    assert audit_row == ("error", "O2: Violence, Harm, or Cruelty", 1)
    assert requests[-1] == ("POST", "https://api.x.com/2/users/bot-user-id/blocking")


def test_e2e_allowlisted_sender_skips_before_dm_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        raise AssertionError("DM lookup should not happen for allowlisted sender")

    run(insert_event_row(db_path, event_id="prior-event", sender_id="sender-allow"))

    async def seed_allowlist() -> None:
        from dmguard.db import get_connection
        from dmguard.repo_senders import insert_allowed_sender

        async with get_connection(db_path) as connection:
            await insert_allowed_sender(
                connection,
                sender_id="sender-allow",
                source_event_id="prior-event",
            )
            await connection.commit()

    run(seed_allowlist())

    client = create_app_client(
        db_path,
        tmp_path,
        monkeypatch,
        handler=handler,
        classifier_cmd=safe_classifier_cmd(),
    )

    with client:
        response = post_signed_webhook(
            client,
            build_webhook_payload("event-allow", "sender-allow"),
        )
        assert response.status_code == 200

        job_id = run(find_job_id(db_path, "event-allow"))
        run(wait_for_job_status(db_path, job_id, JobStatus.skipped.value))

    audit_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT outcome, block_attempted
            FROM moderation_audit
            WHERE job_id = ?
            """,
            (job_id,),
        )
    )

    assert audit_row == ("skipped_allowlist", 0)
    assert requests == []


def test_e2e_text_only_dm_is_logged_without_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        assert request.headers["Authorization"] == "Bearer access-token"

        if request.method == "GET" and request.url.path == "/2/dm_events/event-text":
            return httpx.Response(
                200,
                json=build_dm_event_response(
                    event_id="event-text",
                    sender_id="sender-text",
                ),
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_app_client(
        db_path,
        tmp_path,
        monkeypatch,
        handler=handler,
        classifier_cmd=safe_classifier_cmd(),
    )

    with client:
        response = post_signed_webhook(
            client,
            build_webhook_payload("event-text", "sender-text"),
        )
        assert response.status_code == 200

        job_id = run(find_job_id(db_path, "event-text"))
        run(wait_for_job_status(db_path, job_id, JobStatus.done.value))

    audit_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT outcome, block_attempted
            FROM moderation_audit
            WHERE job_id = ?
            """,
            (job_id,),
        )
    )

    assert audit_row == ("text_only_logged", 0)
    assert requests == [
        (
            "GET",
            "https://api.x.com/2/dm_events/event-text?event_fields=attachments%2Ccreated_at%2Csender_id%2Ctext&expansions=attachments.media_keys%2Csender_id&media.fields=type%2Curl%2Cpreview_image_url%2Cvariants",
        ),
    ]


def test_e2e_classifier_timeout_marks_job_error_without_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dmguard.classifier_runner as classifier_runner

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-timeout", sender_id="sender-timeout"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-timeout",
            next_run_at="2026-03-11T00:00:00Z",
            attempt=3,
        )
    )
    requests: list[tuple[str, str]] = []
    classifier_script_path = tmp_path / "classifier_timeout.py"
    classifier_script_path.write_text(
        "import sys\nimport time\n\ntime.sleep(5)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(classifier_runner, "CLASSIFIER_TIMEOUT_SECONDS", 0.1)

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        assert request.headers["Authorization"] == "Bearer access-token"

        if request.method == "GET" and request.url.path == "/2/dm_events/event-timeout":
            return httpx.Response(
                200,
                json=build_dm_event_response(
                    event_id="event-timeout",
                    sender_id="sender-timeout",
                    media=[
                        {
                            "media_key": "3_1",
                            "type": "photo",
                            "url": "https://media.example.com/timeout-photo.jpg",
                        }
                    ],
                    media_keys=["3_1"],
                ),
            )

        if (
            request.method == "GET"
            and str(request.url) == "https://media.example.com/timeout-photo.jpg"
        ):
            return httpx.Response(200, content=b"timeout-photo-bytes")

        if request.method == "POST":
            raise AssertionError(
                "Block request should not happen on classifier timeout"
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = create_app_client(
        db_path,
        tmp_path,
        monkeypatch,
        handler=handler,
        classifier_cmd=[sys.executable, str(classifier_script_path)],
    )

    with client:
        run(wait_for_job_status(db_path, job_id, JobStatus.error.value))

    error_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT error_type
            FROM job_errors
            WHERE job_id = ?
            LIMIT 1
            """,
            (job_id,),
        )
    )
    blocked_row = run(
        fetch_one_row(
            db_path,
            """
            SELECT sender_id
            FROM blocked_senders
            WHERE sender_id = ?
            """,
            ("sender-timeout",),
        )
    )

    assert error_row == ("ClassifierTimeoutError",)
    assert blocked_row is None
    assert requests == [
        (
            "GET",
            "https://api.x.com/2/dm_events/event-timeout?event_fields=attachments%2Ccreated_at%2Csender_id%2Ctext&expansions=attachments.media_keys%2Csender_id&media.fields=type%2Curl%2Cpreview_image_url%2Cvariants",
        ),
        ("GET", "https://media.example.com/timeout-photo.jpg"),
    ]


def test_e2e_startup_recovery_resets_stale_processing_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dmguard.app as app_module
    from dmguard import scheduler

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-stale", sender_id="sender-stale"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-stale",
            next_run_at="2099-01-01T00:00:00Z",
            status=JobStatus.processing,
            stage=JobStage.fetch_dm,
            attempt=1,
            processing_started_at="2026-03-11T09:00:00Z",
        )
    )
    monkeypatch.setattr(scheduler, "_utc_now", lambda: "2026-03-11T10:00:00Z")
    worker_started = threading.Event()
    worker_cancelled = threading.Event()

    async def fake_worker_loop(
        db_path_arg: Path,
        dispatch_fn,
        *,
        poll_interval_seconds: float = 5,
        logger=None,
    ) -> None:
        del dispatch_fn, logger
        assert db_path_arg == db_path
        assert poll_interval_seconds == 0.01
        worker_started.set()

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    monkeypatch.setattr(app_module, "worker_loop", fake_worker_loop)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request during recovery test: {request.url}")

    client = create_app_client(
        db_path,
        tmp_path,
        monkeypatch,
        handler=handler,
        classifier_cmd=safe_classifier_cmd(),
    )

    with client:
        assert worker_started.wait(timeout=1)
        recovered_job = run(fetch_job(db_path, job_id))

    assert worker_cancelled.wait(timeout=1)
    assert recovered_job is not None
    assert recovered_job["status"] == JobStatus.queued.value
    assert recovered_job["processing_started_at"] is None
