from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.conftest import bootstrap_database, insert_event_row, insert_job_row, run
from dmguard.job_machine import JobStage, JobStatus


def utc_iso(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


async def fetch_job(db_path: Path, job_id: int) -> dict[str, object] | None:
    from dmguard.db import get_connection
    from dmguard.repo_jobs import get_job

    async with get_connection(db_path) as connection:
        return await get_job(connection, job_id)


def test_dequeue_next_job_returns_oldest_runnable_job(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    now = datetime.now(timezone.utc).replace(microsecond=0)

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    run(insert_event_row(db_path, event_id="event-2"))
    run(insert_event_row(db_path, event_id="event-3"))
    run(insert_event_row(db_path, event_id="event-4"))

    oldest_job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at=utc_iso(now - timedelta(minutes=2)),
        )
    )
    run(
        insert_job_row(
            db_path,
            event_id="event-2",
            next_run_at=utc_iso(now - timedelta(minutes=1)),
        )
    )
    run(
        insert_job_row(
            db_path,
            event_id="event-3",
            next_run_at=utc_iso(now + timedelta(minutes=1)),
        )
    )
    run(
        insert_job_row(
            db_path,
            event_id="event-4",
            next_run_at=utc_iso(now - timedelta(minutes=3)),
            status=JobStatus.processing,
        )
    )

    async def scenario() -> dict[str, object] | None:
        from dmguard.db import get_connection
        from dmguard.scheduler import dequeue_next_job

        async with get_connection(db_path) as connection:
            return await dequeue_next_job(connection)

    job = run(scenario())

    assert job is not None
    assert job["job_id"] == oldest_job_id
    assert job["event_id"] == "event-1"
    assert job["status"] == JobStatus.queued.value


def test_claim_job_is_idempotent_and_sets_processing_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T00:00:00Z",
        )
    )

    async def scenario() -> tuple[bool, bool, dict[str, object] | None]:
        from dmguard.db import get_connection
        from dmguard.repo_jobs import get_job
        from dmguard.scheduler import claim_job

        async with get_connection(db_path) as connection:
            await connection.execute(
                """
                UPDATE jobs
                SET updated_at = '2000-01-01T00:00:00Z'
                WHERE job_id = ?
                """,
                (job_id,),
            )
            await connection.commit()

        async with get_connection(db_path) as connection:
            first_claim = await claim_job(connection, job_id)
            second_claim = await claim_job(connection, job_id)
            await connection.commit()
            job = await get_job(connection, job_id)

        return first_claim, second_claim, job

    first_claim, second_claim, job = run(scenario())

    assert first_claim is True
    assert second_claim is False
    assert job is not None
    assert job["status"] == JobStatus.processing.value
    assert job["attempt"] == 1
    assert job["processing_started_at"] is not None
    assert job["updated_at"] != "2000-01-01T00:00:00Z"


def test_advance_stage_resets_attempt_and_updates_timestamp(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T00:00:00Z",
            status=JobStatus.processing,
            attempt=2,
        )
    )

    async def scenario() -> tuple[bool, dict[str, object] | None]:
        from dmguard.db import get_connection
        from dmguard.repo_jobs import get_job
        from dmguard.scheduler import advance_stage

        async with get_connection(db_path) as connection:
            await connection.execute(
                """
                UPDATE jobs
                SET updated_at = '2000-01-01T00:00:00Z'
                WHERE job_id = ?
                """,
                (job_id,),
            )
            await connection.commit()

        async with get_connection(db_path) as connection:
            advanced = await advance_stage(
                connection,
                job_id,
                JobStage.download_media,
            )
            await connection.commit()
            job = await get_job(connection, job_id)

        return advanced, job

    advanced, job = run(scenario())

    assert advanced is True
    assert job is not None
    assert job["stage"] == JobStage.download_media.value
    assert job["attempt"] == 0
    assert job["updated_at"] != "2000-01-01T00:00:00Z"


@pytest.mark.parametrize(
    ("terminal_status"),
    [
        JobStatus.done,
        JobStatus.error,
        JobStatus.skipped,
    ],
)
def test_complete_job_sets_terminal_status(
    tmp_path: Path,
    terminal_status: JobStatus,
) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T00:00:00Z",
            status=JobStatus.processing,
        )
    )

    async def scenario() -> tuple[bool, dict[str, object] | None]:
        from dmguard.db import get_connection
        from dmguard.repo_jobs import get_job
        from dmguard.scheduler import complete_job

        async with get_connection(db_path) as connection:
            await connection.execute(
                """
                UPDATE jobs
                SET updated_at = '2000-01-01T00:00:00Z'
                WHERE job_id = ?
                """,
                (job_id,),
            )
            await connection.commit()

        async with get_connection(db_path) as connection:
            completed = await complete_job(connection, job_id, terminal_status)
            await connection.commit()
            job = await get_job(connection, job_id)

        return completed, job

    completed, job = run(scenario())

    assert completed is True
    assert job is not None
    assert job["status"] == terminal_status.value
    assert job["updated_at"] != "2000-01-01T00:00:00Z"


def test_complete_job_rejects_non_terminal_status(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T00:00:00Z",
            status=JobStatus.processing,
        )
    )

    async def scenario() -> None:
        from dmguard.db import get_connection
        from dmguard.scheduler import complete_job

        async with get_connection(db_path) as connection:
            await complete_job(connection, job_id, JobStatus.processing)

    with pytest.raises(ValueError, match="terminal"):
        run(scenario())


@pytest.mark.parametrize(
    ("attempt", "expected_next_run_at"),
    [
        (1, "2026-03-11T10:00:10Z"),
        (2, "2026-03-11T10:01:00Z"),
        (3, "2026-03-11T10:05:00Z"),
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
            attempt=attempt,
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

    async def scenario() -> list[dict[str, object]]:
        from dmguard.db import get_connection

        async with get_connection(db_path) as connection:
            reset_jobs = await scheduler.reset_stale_jobs(
                connection,
                stale_threshold_minutes=30,
            )
            await connection.commit()
            return reset_jobs

    reset_jobs = run(scenario())
    stale_job = run(fetch_job(db_path, stale_job_id))
    threshold_job = run(fetch_job(db_path, threshold_job_id))
    fresh_job = run(fetch_job(db_path, fresh_job_id))
    queued_job = run(fetch_job(db_path, queued_job_id))

    assert len(reset_jobs) == 1
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
