import logging

import aiosqlite

from dmguard.scheduler import reset_stale_jobs


async def recover_stale_jobs(
    connection: aiosqlite.Connection,
    logger: logging.Logger,
    stale_threshold_minutes: int = 30,
) -> int:
    reset_jobs = await reset_stale_jobs(
        connection,
        stale_threshold_minutes=stale_threshold_minutes,
    )

    for job in reset_jobs:
        logger.info(
            "Recovered stale job job_id=%s processing_started_at=%s",
            job["job_id"],
            job["processing_started_at"],
        )

    return len(reset_jobs)


__all__ = ["recover_stale_jobs"]
