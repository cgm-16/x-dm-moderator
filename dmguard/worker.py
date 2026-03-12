import asyncio
from collections.abc import Awaitable, Callable
import logging
from pathlib import Path

from dmguard.db import get_connection
from dmguard.job_machine import JobStatus
from dmguard.scheduler import claim_job, complete_job, dequeue_next_job, schedule_retry


POLL_INTERVAL_SECONDS = 5
DispatchFn = Callable[[dict[str, object]], Awaitable[None]]


async def _claim_next_job(db_path: Path) -> dict[str, object] | None:
    async with get_connection(db_path) as connection:
        job = await dequeue_next_job(connection)
        if job is None:
            return None

        job_id = int(job["job_id"])
        claimed = await claim_job(connection, job_id)
        if not claimed:
            await connection.rollback()
            return None

        await connection.commit()

    claimed_job = dict(job)
    claimed_job["status"] = JobStatus.processing.value
    claimed_job["attempt"] = int(job["attempt"]) + 1
    return claimed_job


async def _mark_job_done(db_path: Path, job_id: int) -> None:
    async with get_connection(db_path) as connection:
        await complete_job(connection, job_id, JobStatus.done)
        await connection.commit()


async def _retry_or_error(
    db_path: Path,
    job_id: int,
    attempt: int,
    logger: logging.Logger,
) -> None:
    async with get_connection(db_path) as connection:
        try:
            scheduled_for = await schedule_retry(connection, job_id, attempt)
        except ValueError:
            await complete_job(connection, job_id, JobStatus.error)
            await connection.commit()
            logger.exception(
                "Worker dispatch failed and retries were exhausted job_id=%s attempt=%s",
                job_id,
                attempt,
            )
            return

        await connection.commit()
        logger.exception(
            "Worker dispatch failed; scheduled retry job_id=%s attempt=%s next_run_at=%s",
            job_id,
            attempt,
            scheduled_for,
        )


async def worker_loop(
    db_path: Path,
    dispatch_fn: DispatchFn,
    *,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    logger: logging.Logger | None = None,
) -> None:
    worker_logger = logger or logging.getLogger("dmguard")

    while True:
        try:
            job = await _claim_next_job(db_path)
            if job is not None:
                job_id = int(job["job_id"])
                attempt = int(job["attempt"])

                try:
                    await dispatch_fn(job)
                except Exception:
                    await _retry_or_error(
                        db_path,
                        job_id,
                        attempt,
                        worker_logger,
                    )
                else:
                    await _mark_job_done(db_path, job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            worker_logger.exception("Worker loop iteration failed")

        await asyncio.sleep(poll_interval_seconds)


__all__ = ["POLL_INTERVAL_SECONDS", "worker_loop"]
