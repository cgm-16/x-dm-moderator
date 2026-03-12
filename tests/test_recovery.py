import io
import logging
from pathlib import Path

from dmguard.job_machine import JobStage, JobStatus
from tests.conftest import (
    bootstrap_database,
    clear_logger,
    insert_event_row,
    insert_job_row,
    run,
)


async def fetch_job(db_path: Path, job_id: int) -> dict[str, object] | None:
    from dmguard.db import get_connection
    from dmguard.repo_jobs import get_job

    async with get_connection(db_path) as connection:
        return await get_job(connection, job_id)


def build_logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    logger = logging.getLogger(name)
    clear_logger(name)

    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    return logger, stream


def test_recover_stale_jobs_resets_stale_rows_and_logs_each_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dmguard.db import get_connection
    from dmguard import recovery
    from dmguard import scheduler

    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-stale"))
    run(insert_event_row(db_path, event_id="event-fresh"))
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

    logger, stream = build_logger("dmguard.test.recovery")
    monkeypatch.setattr(scheduler, "_utc_now", lambda: "2026-03-11T10:00:00Z")

    async def scenario() -> int:
        async with get_connection(db_path) as connection:
            reset_count = await recovery.recover_stale_jobs(connection, logger)
            await connection.commit()
            return reset_count

    reset_count = run(scenario())
    stale_job = run(fetch_job(db_path, stale_job_id))
    fresh_job = run(fetch_job(db_path, fresh_job_id))

    assert reset_count == 1
    assert stale_job is not None
    assert stale_job["status"] == JobStatus.queued.value
    assert stale_job["processing_started_at"] is None
    assert fresh_job is not None
    assert fresh_job["status"] == JobStatus.processing.value
    assert fresh_job["processing_started_at"] == "2026-03-11T09:30:01Z"
    assert (
        "Recovered stale job job_id="
        f"{stale_job_id} processing_started_at=2026-03-11T09:29:59Z"
    ) in stream.getvalue()

    clear_logger("dmguard.test.recovery")


def test_recover_stale_jobs_is_noop_without_stale_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dmguard.db import get_connection
    from dmguard import recovery
    from dmguard import scheduler

    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-fresh"))
    run(
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

    logger, stream = build_logger("dmguard.test.recovery.noop")
    monkeypatch.setattr(scheduler, "_utc_now", lambda: "2026-03-11T10:00:00Z")

    async def scenario() -> int:
        async with get_connection(db_path) as connection:
            reset_count = await recovery.recover_stale_jobs(connection, logger)
            await connection.commit()
            return reset_count

    reset_count = run(scenario())

    assert reset_count == 0
    assert stream.getvalue() == ""

    clear_logger("dmguard.test.recovery.noop")
