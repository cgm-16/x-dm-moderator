from datetime import datetime, timedelta, timezone
import logging

import aiosqlite

from dmguard.repo_jobs import list_stale_processing_jobs
from dmguard.scheduler import reset_stale_jobs


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _stale_before(stale_threshold_minutes: int) -> str:
    now = datetime.fromisoformat(_utc_now().replace("Z", "+00:00"))
    stale_before = now - timedelta(minutes=stale_threshold_minutes)
    return (
        stale_before.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


async def recover_stale_jobs(
    connection: aiosqlite.Connection,
    logger: logging.Logger,
    stale_threshold_minutes: int = 30,
) -> int:
    stale_jobs = await list_stale_processing_jobs(
        connection,
        before=_stale_before(stale_threshold_minutes),
    )
    reset_count = await reset_stale_jobs(
        connection,
        stale_threshold_minutes=stale_threshold_minutes,
    )

    for stale_job in stale_jobs[:reset_count]:
        logger.info(
            "Recovered stale job job_id=%s processing_started_at=%s",
            stale_job["job_id"],
            stale_job["processing_started_at"],
        )

    return reset_count


__all__ = ["recover_stale_jobs"]
