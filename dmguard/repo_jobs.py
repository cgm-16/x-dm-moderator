from enum import Enum

import aiosqlite

from dmguard.job_machine import JobStage, JobStatus
from dmguard.repo_common import fetch_all_dicts, fetch_one_dict

_UNCHANGED = object()


def _enum_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value

    return value


async def insert_job(
    connection: aiosqlite.Connection,
    *,
    event_id: str,
    status: JobStatus | str,
    stage: JobStage | str,
    next_run_at: str,
    attempt: int = 0,
    processing_started_at: str | None = None,
    sender_id: str | None = None,
) -> int:
    cursor = await connection.execute(
        """
        INSERT INTO jobs (
          event_id,
          status,
          stage,
          attempt,
          next_run_at,
          processing_started_at,
          sender_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            _enum_value(status),
            _enum_value(stage),
            attempt,
            next_run_at,
            processing_started_at,
            sender_id,
        ),
    )

    await cursor.close()
    return int(cursor.lastrowid)


async def get_job(
    connection: aiosqlite.Connection,
    job_id: int,
) -> dict[str, object] | None:
    return await fetch_one_dict(
        connection,
        """
        SELECT
          job_id,
          event_id,
          status,
          stage,
          attempt,
          next_run_at,
          processing_started_at,
          created_at,
          updated_at,
          sender_id
        FROM jobs
        WHERE job_id = ?
        """,
        (job_id,),
    )


async def update_job_status(
    connection: aiosqlite.Connection,
    job_id: int,
    *,
    status: JobStatus | str,
    stage: JobStage | str | None | object = _UNCHANGED,
    attempt: int | object = _UNCHANGED,
    next_run_at: str | None | object = _UNCHANGED,
    processing_started_at: str | None | object = _UNCHANGED,
    sender_id: str | None | object = _UNCHANGED,
) -> bool:
    assignments = ["status = ?", "updated_at = datetime('now')"]
    params: list[object] = [_enum_value(status)]

    if stage is not _UNCHANGED:
        assignments.append("stage = ?")
        params.append(_enum_value(stage))

    if attempt is not _UNCHANGED:
        assignments.append("attempt = ?")
        params.append(attempt)

    if next_run_at is not _UNCHANGED:
        assignments.append("next_run_at = ?")
        params.append(next_run_at)

    if processing_started_at is not _UNCHANGED:
        assignments.append("processing_started_at = ?")
        params.append(processing_started_at)

    if sender_id is not _UNCHANGED:
        assignments.append("sender_id = ?")
        params.append(sender_id)

    params.append(job_id)
    cursor = await connection.execute(
        f"""
        UPDATE jobs
        SET {", ".join(assignments)}
        WHERE job_id = ?
        """,
        params,
    )

    await cursor.close()
    return cursor.rowcount == 1


async def list_runnable_jobs(
    connection: aiosqlite.Connection,
    *,
    now: str,
) -> list[dict[str, object]]:
    return await fetch_all_dicts(
        connection,
        """
        SELECT
          job_id,
          event_id,
          status,
          stage,
          attempt,
          next_run_at,
          processing_started_at,
          created_at,
          updated_at,
          sender_id
        FROM jobs
        WHERE status = ? AND next_run_at <= ?
        ORDER BY next_run_at ASC, job_id ASC
        """,
        (JobStatus.queued.value, now),
    )


async def list_stale_processing_jobs(
    connection: aiosqlite.Connection,
    *,
    before: str,
) -> list[dict[str, object]]:
    return await fetch_all_dicts(
        connection,
        """
        SELECT
          job_id,
          event_id,
          status,
          stage,
          attempt,
          next_run_at,
          processing_started_at,
          created_at,
          updated_at,
          sender_id
        FROM jobs
        WHERE status = ? AND processing_started_at IS NOT NULL AND processing_started_at < ?
        ORDER BY processing_started_at ASC, job_id ASC
        """,
        (JobStatus.processing.value, before),
    )


__all__ = [
    "get_job",
    "insert_job",
    "list_runnable_jobs",
    "list_stale_processing_jobs",
    "update_job_status",
]
