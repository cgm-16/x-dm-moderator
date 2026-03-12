from pathlib import Path

import pytest

from tests.conftest import run
from dmguard.job_machine import JobStage, JobStatus


async def bootstrap_database(db_path: Path) -> None:
    from dmguard.db import get_connection
    from dmguard.schema import bootstrap_schema

    async with get_connection(db_path) as connection:
        await bootstrap_schema(connection)


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


async def fetch_job(db_path: Path, job_id: int) -> dict[str, object] | None:
    from dmguard.db import get_connection
    from dmguard.repo_jobs import get_job

    async with get_connection(db_path) as connection:
        return await get_job(connection, job_id)


@pytest.mark.parametrize(
    ("attempt", "expected_next_run_at"),
    [
        (0, "2026-03-11T10:00:10Z"),
        (1, "2026-03-11T10:01:00Z"),
        (2, "2026-03-11T10:05:00Z"),
    ],
)
def test_schedule_retry_sets_expected_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt: int,
    expected_next_run_at: str,
) -> None:
    from dmguard import scheduler

    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T09:59:00Z",
            status=JobStatus.processing,
            stage=JobStage.classify,
            attempt=0,
            processing_started_at="2026-03-11T09:59:00Z",
        )
    )
    monkeypatch.setattr(scheduler, "_utc_now", lambda: "2026-03-11T10:00:00Z")

    async def scenario() -> str:
        from dmguard.db import get_connection

        async with get_connection(db_path) as connection:
            scheduled_for = await scheduler.schedule_retry(
                connection,
                job_id,
                attempt,
            )
            await connection.commit()
            return scheduled_for

    scheduled_for = run(scenario())
    job = run(fetch_job(db_path, job_id))

    assert scheduled_for == expected_next_run_at
    assert job is not None
    assert job["status"] == JobStatus.queued.value
    assert job["stage"] == JobStage.classify.value
    assert job["attempt"] == attempt
    assert job["next_run_at"] == expected_next_run_at
    assert job["processing_started_at"] is None


def test_schedule_429_retry_preserves_attempt_and_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard import scheduler

    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T09:59:00Z",
            status=JobStatus.processing,
            stage=JobStage.block,
            attempt=2,
            processing_started_at="2026-03-11T09:59:30Z",
        )
    )
    monkeypatch.setattr(scheduler, "_utc_now", lambda: "2026-03-11T10:00:00Z")

    async def scenario() -> str:
        from dmguard.db import get_connection

        async with get_connection(db_path) as connection:
            scheduled_for = await scheduler.schedule_429_retry(
                connection,
                job_id,
                retry_after_seconds=17,
            )
            await connection.commit()
            return scheduled_for

    scheduled_for = run(scenario())
    job = run(fetch_job(db_path, job_id))

    assert scheduled_for == "2026-03-11T10:00:17Z"
    assert job is not None
    assert job["status"] == JobStatus.queued.value
    assert job["stage"] == JobStage.block.value
    assert job["attempt"] == 2
    assert job["next_run_at"] == "2026-03-11T10:00:17Z"
    assert job["processing_started_at"] is None


def test_reset_stale_jobs_resets_only_rows_older_than_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard import scheduler

    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-stale"))
    run(insert_event_row(db_path, event_id="event-threshold"))
    run(insert_event_row(db_path, event_id="event-fresh"))
    run(insert_event_row(db_path, event_id="event-queued"))

    stale_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-stale",
            next_run_at="2026-03-11T09:00:00Z",
            status=JobStatus.processing,
            stage=JobStage.download_media,
            attempt=2,
            processing_started_at="2026-03-11T09:29:59Z",
        )
    )
    threshold_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-threshold",
            next_run_at="2026-03-11T09:05:00Z",
            status=JobStatus.processing,
            stage=JobStage.classify,
            attempt=1,
            processing_started_at="2026-03-11T09:30:00Z",
        )
    )
    fresh_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-fresh",
            next_run_at="2026-03-11T09:10:00Z",
            status=JobStatus.processing,
            stage=JobStage.block,
            attempt=1,
            processing_started_at="2026-03-11T09:30:01Z",
        )
    )
    queued_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-queued",
            next_run_at="2026-03-11T09:00:00Z",
            status=JobStatus.queued,
            stage=JobStage.fetch_dm,
            attempt=0,
        )
    )
    monkeypatch.setattr(scheduler, "_utc_now", lambda: "2026-03-11T10:00:00Z")

    async def scenario() -> int:
        from dmguard.db import get_connection

        async with get_connection(db_path) as connection:
            reset_count = await scheduler.reset_stale_jobs(
                connection,
                stale_threshold_minutes=30,
            )
            await connection.commit()
            return reset_count

    reset_count = run(scenario())
    stale_job = run(fetch_job(db_path, stale_job_id))
    threshold_job = run(fetch_job(db_path, threshold_job_id))
    fresh_job = run(fetch_job(db_path, fresh_job_id))
    queued_job = run(fetch_job(db_path, queued_job_id))

    assert reset_count == 1
    assert stale_job is not None
    assert stale_job["status"] == JobStatus.queued.value
    assert stale_job["stage"] == JobStage.download_media.value
    assert stale_job["attempt"] == 2
    assert stale_job["next_run_at"] == "2026-03-11T10:00:00Z"
    assert stale_job["processing_started_at"] is None

    assert threshold_job is not None
    assert threshold_job["status"] == JobStatus.processing.value
    assert threshold_job["next_run_at"] == "2026-03-11T09:05:00Z"
    assert threshold_job["processing_started_at"] == "2026-03-11T09:30:00Z"

    assert fresh_job is not None
    assert fresh_job["status"] == JobStatus.processing.value
    assert fresh_job["next_run_at"] == "2026-03-11T09:10:00Z"
    assert fresh_job["processing_started_at"] == "2026-03-11T09:30:01Z"

    assert queued_job is not None
    assert queued_job["status"] == JobStatus.queued.value
    assert queued_job["next_run_at"] == "2026-03-11T09:00:00Z"
