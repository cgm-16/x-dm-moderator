from datetime import datetime, timedelta, timezone
from enum import Enum

import aiosqlite

from dmguard.job_machine import JobStage, JobStatus, is_terminal, next_backoff_seconds
from dmguard.repo_jobs import (
    list_runnable_jobs,
    list_stale_processing_jobs,
    update_job_status,
)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _parse_utc(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def _format_utc(timestamp: datetime) -> str:
    return (
        timestamp.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


async def dequeue_next_job(
    connection: aiosqlite.Connection,
) -> dict[str, object] | None:
    jobs = await list_runnable_jobs(connection, now=_utc_now())
    return jobs[0] if jobs else None


async def claim_job(
    connection: aiosqlite.Connection,
    job_id: int,
) -> bool:
    now = _utc_now()
    cursor = await connection.execute(
        """
        UPDATE jobs
        SET
          status = ?,
          attempt = attempt + 1,
          processing_started_at = ?,
          updated_at = ?
        WHERE job_id = ? AND status = ?
        """,
        (
            JobStatus.processing.value,
            now,
            now,
            job_id,
            JobStatus.queued.value,
        ),
    )

    await cursor.close()
    return cursor.rowcount == 1


async def advance_stage(
    connection: aiosqlite.Connection,
    job_id: int,
    new_stage: JobStage | str,
) -> bool:
    stage_value = new_stage.value if isinstance(new_stage, Enum) else new_stage
    cursor = await connection.execute(
        """
        UPDATE jobs
        SET
          stage = ?,
          attempt = 0,
          updated_at = ?
        WHERE job_id = ?
        """,
        (stage_value, _utc_now(), job_id),
    )

    await cursor.close()
    return cursor.rowcount == 1


async def complete_job(
    connection: aiosqlite.Connection,
    job_id: int,
    status: JobStatus | str,
) -> bool:
    if isinstance(status, str):
        status = JobStatus(status)
    if not is_terminal(status):
        raise ValueError("complete_job requires a terminal status")

    return await update_job_status(connection, job_id, status=status)


async def schedule_retry(
    connection: aiosqlite.Connection,
    job_id: int,
    attempt: int,
) -> str:
    scheduled_for = _format_utc(
        _parse_utc(_utc_now()) + timedelta(seconds=next_backoff_seconds(attempt))
    )
    updated = await update_job_status(
        connection,
        job_id,
        status=JobStatus.queued,
        attempt=attempt,
        next_run_at=scheduled_for,
        processing_started_at=None,
    )
    if not updated:
        raise ValueError(f"job {job_id} does not exist")

    return scheduled_for


async def schedule_429_retry(
    connection: aiosqlite.Connection,
    job_id: int,
    retry_after_seconds: int,
) -> str:
    scheduled_for = _format_utc(
        _parse_utc(_utc_now()) + timedelta(seconds=retry_after_seconds)
    )
    updated = await update_job_status(
        connection,
        job_id,
        status=JobStatus.queued,
        next_run_at=scheduled_for,
        processing_started_at=None,
    )
    if not updated:
        raise ValueError(f"job {job_id} does not exist")

    return scheduled_for


async def reset_stale_jobs(
    connection: aiosqlite.Connection,
    stale_threshold_minutes: int = 30,
) -> list[dict[str, object]]:
    now = _parse_utc(_utc_now())
    stale_before = _format_utc(now - timedelta(minutes=stale_threshold_minutes))
    stale_jobs = await list_stale_processing_jobs(connection, before=stale_before)
    reset_jobs: list[dict[str, object]] = []

    for stale_job in stale_jobs:
        updated = await update_job_status(
            connection,
            int(stale_job["job_id"]),
            status=JobStatus.queued,
            next_run_at=_format_utc(now),
            processing_started_at=None,
        )
        if updated:
            reset_jobs.append(stale_job)

    return reset_jobs


__all__ = [
    "advance_stage",
    "claim_job",
    "complete_job",
    "dequeue_next_job",
    "reset_stale_jobs",
    "schedule_429_retry",
    "schedule_retry",
]
