from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypeVar

import aiosqlite

from dmguard.job_machine import JobStatus, is_terminal
from dmguard.repo_common import fetch_all_dicts

_SQLITE_MAX_VARIABLES = 32766
_TERMINAL_JOB_STATUSES = tuple(
    status.value for status in JobStatus if is_terminal(status)
)

T = TypeVar("T")


@dataclass(frozen=True)
class PruneResult:
    job_errors_deleted: int = 0
    jobs_deleted: int = 0
    webhook_events_deleted: int = 0
    moderation_audit_deleted: int = 0
    rejected_requests_deleted: int = 0


async def prune_old_data(
    connection: aiosqlite.Connection,
    retention_days: int = 30,
) -> PruneResult:
    cutoff_modifier = f"-{retention_days} days"
    status_placeholders = ", ".join("?" for _ in _TERMINAL_JOB_STATUSES)
    prunable_jobs = await fetch_all_dicts(
        connection,
        f"""
        SELECT job_id, event_id
        FROM jobs
        WHERE status IN ({status_placeholders})
          AND datetime(updated_at) <= datetime('now', ?)
        ORDER BY job_id ASC
        """,
        (*_TERMINAL_JOB_STATUSES, cutoff_modifier),
    )
    job_ids = [int(job["job_id"]) for job in prunable_jobs]
    event_ids = [str(job["event_id"]) for job in prunable_jobs]

    job_errors_deleted = await _delete_by_ids(
        connection,
        table="job_errors",
        column="job_id",
        values=job_ids,
    )
    jobs_deleted = await _delete_by_ids(
        connection,
        table="jobs",
        column="job_id",
        values=job_ids,
    )
    webhook_events_deleted = await _delete_pruned_webhook_events(
        connection,
        event_ids=event_ids,
        cutoff_modifier=cutoff_modifier,
    )
    moderation_audit_deleted = await _delete_older_than(
        connection,
        table="moderation_audit",
        column="created_at",
        cutoff_modifier=cutoff_modifier,
    )
    rejected_requests_deleted = await _delete_older_than(
        connection,
        table="rejected_requests",
        column="received_at",
        cutoff_modifier=cutoff_modifier,
    )

    return PruneResult(
        job_errors_deleted=job_errors_deleted,
        jobs_deleted=jobs_deleted,
        webhook_events_deleted=webhook_events_deleted,
        moderation_audit_deleted=moderation_audit_deleted,
        rejected_requests_deleted=rejected_requests_deleted,
    )


async def _delete_by_ids(
    connection: aiosqlite.Connection,
    *,
    table: str,
    column: str,
    values: list[int],
) -> int:
    if not values:
        return 0

    deleted = 0
    for batch in _iter_batches(values, batch_size=_SQLITE_MAX_VARIABLES):
        placeholders = ", ".join("?" for _ in batch)
        cursor = await connection.execute(
            f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
            batch,
        )

        try:
            deleted += cursor.rowcount
        finally:
            await cursor.close()

    return deleted


async def _delete_pruned_webhook_events(
    connection: aiosqlite.Connection,
    *,
    event_ids: list[str],
    cutoff_modifier: str,
) -> int:
    if not event_ids:
        return 0

    deleted = 0
    for batch in _iter_batches(event_ids, batch_size=_SQLITE_MAX_VARIABLES - 1):
        placeholders = ", ".join("?" for _ in batch)
        cursor = await connection.execute(
            f"""
            DELETE FROM webhook_events
            WHERE event_id IN ({placeholders})
              AND datetime(received_at) <= datetime('now', ?)
              AND NOT EXISTS (
                SELECT 1
                FROM jobs
                WHERE jobs.event_id = webhook_events.event_id
              )
            """,
            [*batch, cutoff_modifier],
        )

        try:
            deleted += cursor.rowcount
        finally:
            await cursor.close()

    return deleted


async def _delete_older_than(
    connection: aiosqlite.Connection,
    *,
    table: str,
    column: str,
    cutoff_modifier: str,
) -> int:
    cursor = await connection.execute(
        f"""
        DELETE FROM {table}
        WHERE datetime({column}) <= datetime('now', ?)
        """,
        (cutoff_modifier,),
    )

    try:
        return cursor.rowcount
    finally:
        await cursor.close()


def _iter_batches(values: list[T], *, batch_size: int) -> Iterator[list[T]]:
    for start in range(0, len(values), batch_size):
        yield values[start : start + batch_size]


__all__ = ["PruneResult", "prune_old_data"]
