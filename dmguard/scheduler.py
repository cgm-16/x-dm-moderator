from datetime import datetime, timedelta, timezone

import aiosqlite

from dmguard.job_machine import JobStatus, next_backoff_seconds
from dmguard.repo_jobs import list_stale_processing_jobs, update_job_status


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
) -> int:
    now = _parse_utc(_utc_now())
    stale_before = _format_utc(now - timedelta(minutes=stale_threshold_minutes))
    stale_jobs = await list_stale_processing_jobs(connection, before=stale_before)
    reset_count = 0

    for stale_job in stale_jobs:
        updated = await update_job_status(
            connection,
            int(stale_job["job_id"]),
            status=JobStatus.queued,
            next_run_at=_format_utc(now),
            processing_started_at=None,
        )
        if updated:
            reset_count += 1

    return reset_count


__all__ = [
    "reset_stale_jobs",
    "schedule_429_retry",
    "schedule_retry",
]
