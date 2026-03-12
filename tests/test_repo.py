import sqlite3
from pathlib import Path

import pytest

from dmguard.job_machine import JobStage, JobStatus
from tests.conftest import run


async def bootstrap_database(db_path: Path) -> None:
    from dmguard.db import get_connection
    from dmguard.schema import bootstrap_schema

    async with get_connection(db_path) as connection:
        await bootstrap_schema(connection)


async def fetch_row(
    db_path: Path, query: str, params: tuple[object, ...] = ()
) -> tuple:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(query, params)
        row = await cursor.fetchone()

    return row


async def insert_event_row(
    db_path: Path,
    *,
    event_id: str,
    sender_id: str | None = None,
) -> None:
    from dmguard.db import get_connection
    from dmguard.repo_events import insert_event

    async with get_connection(db_path) as connection:
        await insert_event(
            connection,
            event_id=event_id,
            received_at="2026-03-11T00:00:00Z",
            payload_json='{"event_id":"%s"}' % event_id,
            sender_id=sender_id,
        )
        await connection.commit()


async def insert_job_row(
    db_path: Path,
    *,
    event_id: str,
    next_run_at: str,
    status: JobStatus = JobStatus.queued,
    stage: JobStage = JobStage.fetch_dm,
    attempt: int = 0,
    processing_started_at: str | None = None,
) -> int:
    from dmguard.db import get_connection
    from dmguard.repo_jobs import insert_job

    async with get_connection(db_path) as connection:
        job_id = await insert_job(
            connection,
            event_id=event_id,
            status=status,
            stage=stage,
            next_run_at=next_run_at,
            attempt=attempt,
            processing_started_at=processing_started_at,
        )
        await connection.commit()

    return job_id


def test_repo_events_insert_and_get(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    async def scenario() -> dict[str, object] | None:
        from dmguard.db import get_connection
        from dmguard.repo_events import get_event, insert_event

        async with get_connection(db_path) as connection:
            await insert_event(
                connection,
                event_id="event-1",
                received_at="2026-03-11T00:00:00Z",
                payload_json='{"ok":true}',
                sender_id="sender-1",
            )
            await connection.commit()
            return await get_event(connection, "event-1")

    event = run(scenario())

    assert event == {
        "event_id": "event-1",
        "received_at": "2026-03-11T00:00:00Z",
        "payload_json": '{"ok":true}',
        "sender_id": "sender-1",
    }


def test_repo_events_duplicate_event_id_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    async def scenario() -> None:
        from dmguard.db import get_connection
        from dmguard.repo_events import insert_event

        async with get_connection(db_path) as connection:
            await insert_event(
                connection,
                event_id="event-1",
                received_at="2026-03-11T00:00:00Z",
                payload_json="{}",
            )
            await connection.commit()

        async with get_connection(db_path) as connection:
            await insert_event(
                connection,
                event_id="event-1",
                received_at="2026-03-11T00:00:01Z",
                payload_json="{}",
            )
            await connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        run(scenario())


def test_repo_jobs_insert_update_and_get(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1", sender_id="sender-1"))

    async def scenario() -> tuple[int, bool, dict[str, object] | None]:
        from dmguard.db import get_connection
        from dmguard.repo_jobs import get_job, insert_job, update_job_status

        async with get_connection(db_path) as connection:
            job_id = await insert_job(
                connection,
                event_id="event-1",
                status=JobStatus.queued,
                stage=JobStage.fetch_dm,
                next_run_at="2026-03-11T00:00:00Z",
                sender_id="sender-1",
            )
            updated = await update_job_status(
                connection,
                job_id,
                status=JobStatus.processing,
                attempt=1,
                processing_started_at="2026-03-11T00:00:05Z",
            )
            await connection.commit()
            return job_id, updated, await get_job(connection, job_id)

    job_id, updated, job = run(scenario())

    assert job_id > 0
    assert updated is True
    assert job is not None
    assert job["job_id"] == job_id
    assert job["event_id"] == "event-1"
    assert job["status"] == JobStatus.processing.value
    assert job["stage"] == JobStage.fetch_dm.value
    assert job["attempt"] == 1
    assert job["processing_started_at"] == "2026-03-11T00:00:05Z"
    assert job["sender_id"] == "sender-1"


def test_list_runnable_jobs_filters_and_orders_results(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    run(insert_event_row(db_path, event_id="event-2"))
    run(insert_event_row(db_path, event_id="event-3"))
    run(insert_event_row(db_path, event_id="event-4"))

    first_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T09:59:00Z",
        )
    )
    second_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-2",
            next_run_at="2026-03-11T10:00:00Z",
        )
    )
    run(
        insert_job_row(
            db_path,
            event_id="event-3",
            next_run_at="2026-03-11T10:00:01Z",
        )
    )
    run(
        insert_job_row(
            db_path,
            event_id="event-4",
            next_run_at="2026-03-11T09:58:00Z",
            status=JobStatus.processing,
        )
    )

    async def scenario() -> list[dict[str, object]]:
        from dmguard.db import get_connection
        from dmguard.repo_jobs import list_runnable_jobs

        async with get_connection(db_path) as connection:
            return await list_runnable_jobs(connection, now="2026-03-11T10:00:00Z")

    jobs = run(scenario())

    assert [job["job_id"] for job in jobs] == [first_job_id, second_job_id]
    assert [job["event_id"] for job in jobs] == ["event-1", "event-2"]


def test_list_stale_processing_jobs_filters_results(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    run(insert_event_row(db_path, event_id="event-2"))
    run(insert_event_row(db_path, event_id="event-3"))

    stale_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T09:00:00Z",
            status=JobStatus.processing,
            attempt=1,
            processing_started_at="2026-03-11T09:00:00Z",
        )
    )
    run(
        insert_job_row(
            db_path,
            event_id="event-2",
            next_run_at="2026-03-11T09:30:00Z",
            status=JobStatus.processing,
            attempt=1,
            processing_started_at="2026-03-11T09:45:00Z",
        )
    )
    run(
        insert_job_row(
            db_path,
            event_id="event-3",
            next_run_at="2026-03-11T09:00:00Z",
            status=JobStatus.queued,
        )
    )

    async def scenario() -> list[dict[str, object]]:
        from dmguard.db import get_connection
        from dmguard.repo_jobs import list_stale_processing_jobs

        async with get_connection(db_path) as connection:
            return await list_stale_processing_jobs(
                connection,
                before="2026-03-11T09:30:00Z",
            )

    jobs = run(scenario())

    assert [job["job_id"] for job in jobs] == [stale_job_id]
    assert [job["event_id"] for job in jobs] == ["event-1"]


def test_repo_senders_insert_and_read_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    async def scenario() -> tuple[
        dict[str, object] | None,
        dict[str, object] | None,
        dict[str, object] | None,
    ]:
        from dmguard.db import get_connection
        from dmguard.repo_senders import (
            get_allowed_sender,
            get_block_failed_sender,
            get_blocked_sender,
            insert_allowed_sender,
            insert_blocked_sender,
            upsert_block_failed_sender,
        )

        async with get_connection(db_path) as connection:
            await insert_allowed_sender(
                connection,
                sender_id="sender-1",
                source_event_id="event-1",
            )
            await insert_blocked_sender(
                connection,
                sender_id="sender-2",
                source_event_id="event-2",
            )
            await upsert_block_failed_sender(
                connection,
                sender_id="sender-3",
                next_retry_at="2026-03-12T00:00:00Z",
                first_failed_at="2026-03-11T00:00:00Z",
                last_failed_at="2026-03-11T00:00:00Z",
            )
            await upsert_block_failed_sender(
                connection,
                sender_id="sender-3",
                next_retry_at="2026-03-13T00:00:00Z",
                fail_count=2,
                last_failed_at="2026-03-11T01:00:00Z",
            )
            await connection.commit()
            return (
                await get_allowed_sender(connection, "sender-1"),
                await get_blocked_sender(connection, "sender-2"),
                await get_block_failed_sender(connection, "sender-3"),
            )

    allowed_sender, blocked_sender, block_failed_sender = run(scenario())

    assert allowed_sender == {
        "sender_id": "sender-1",
        "created_at": allowed_sender["created_at"],
        "source_event_id": "event-1",
    }
    assert blocked_sender == {
        "sender_id": "sender-2",
        "created_at": blocked_sender["created_at"],
        "source_event_id": "event-2",
    }
    assert block_failed_sender == {
        "sender_id": "sender-3",
        "first_failed_at": "2026-03-11T00:00:00Z",
        "last_failed_at": "2026-03-11T01:00:00Z",
        "next_retry_at": "2026-03-13T00:00:00Z",
        "fail_count": 2,
    }


def test_repo_audit_rejected_and_kv_write_expected_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1", sender_id="sender-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T00:00:00Z",
        )
    )

    async def scenario() -> tuple[int, int, str | None]:
        from dmguard.db import get_connection
        from dmguard.repo_audit import append_audit_row, insert_job_error
        from dmguard.repo_kv import kv_get, kv_set
        from dmguard.repo_rejected import insert_rejected_request

        async with get_connection(db_path) as connection:
            audit_id = await append_audit_row(
                connection,
                job_id=job_id,
                event_id="event-1",
                sender_id="sender-1",
                outcome="safe",
                policy="violence_gore",
                threshold=0.9,
                score=0.01,
                trigger_frame_index=None,
                trigger_time_sec=None,
                block_attempted=False,
            )
            error_id = await insert_job_error(
                connection,
                job_id=job_id,
                stage=JobStage.fetch_dm.value,
                attempt=1,
                error_type="network",
                error_message="boom",
                http_status=500,
            )
            await insert_rejected_request(
                connection,
                received_at="2026-03-11T00:00:00Z",
                remote_ip="127.0.0.1",
                path="/webhooks/x",
                reason="invalid_json",
                body_sha256="abc123",
            )
            await kv_set(
                connection,
                key="token_expiry",
                value="2026-03-12T00:00:00Z",
                updated_at="2026-03-11T00:00:00Z",
            )
            await kv_set(
                connection,
                key="token_expiry",
                value="2026-03-13T00:00:00Z",
                updated_at="2026-03-11T01:00:00Z",
            )
            await connection.commit()
            return audit_id, error_id, await kv_get(connection, "token_expiry")

    audit_id, error_id, kv_value = run(scenario())

    audit_row = run(
        fetch_row(
            db_path,
            """
            SELECT id, job_id, event_id, sender_id, outcome, policy, threshold, score, block_attempted
            FROM moderation_audit
            WHERE id = ?
            """,
            (audit_id,),
        )
    )
    error_row = run(
        fetch_row(
            db_path,
            """
            SELECT id, job_id, stage, attempt, error_type, error_message, http_status
            FROM job_errors
            WHERE id = ?
            """,
            (error_id,),
        )
    )
    rejected_row = run(
        fetch_row(
            db_path,
            """
            SELECT remote_ip, path, reason, body_sha256
            FROM rejected_requests
            """,
        )
    )

    assert audit_row == (
        audit_id,
        job_id,
        "event-1",
        "sender-1",
        "safe",
        "violence_gore",
        0.9,
        0.01,
        0,
    )
    assert error_row == (
        error_id,
        job_id,
        JobStage.fetch_dm.value,
        1,
        "network",
        "boom",
        500,
    )
    assert rejected_row == ("127.0.0.1", "/webhooks/x", "invalid_json", "abc123")
    assert kv_value == "2026-03-13T00:00:00Z"
