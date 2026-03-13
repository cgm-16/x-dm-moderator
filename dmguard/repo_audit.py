import aiosqlite

from dmguard.setup_logger import redact_secrets


async def append_audit_row(
    connection: aiosqlite.Connection,
    *,
    job_id: int,
    event_id: str,
    sender_id: str,
    outcome: str,
    policy: str,
    category_code: str | None,
    rationale: str | None,
    trigger_frame_index: int | None,
    trigger_time_sec: float | None,
    block_attempted: bool,
) -> int:
    cursor = await connection.execute(
        """
        INSERT INTO moderation_audit (
          job_id,
          event_id,
          sender_id,
          outcome,
          policy,
          category_code,
          rationale,
          trigger_frame_index,
          trigger_time_sec,
          block_attempted
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            event_id,
            sender_id,
            outcome,
            policy,
            category_code,
            rationale,
            trigger_frame_index,
            trigger_time_sec,
            block_attempted,
        ),
    )

    await cursor.close()
    return int(cursor.lastrowid)


async def record_job_error(
    connection: aiosqlite.Connection,
    *,
    job_id: int,
    stage: str | None,
    attempt: int | None,
    error_type: str | None,
    error_message: str | None,
    http_status: int | None,
) -> int:
    redacted_error_message = None
    if error_message is not None:
        redacted_error_message = redact_secrets(error_message)

    cursor = await connection.execute(
        """
        INSERT INTO job_errors (
          job_id,
          stage,
          attempt,
          error_type,
          error_message,
          http_status
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            stage,
            attempt,
            error_type,
            redacted_error_message,
            http_status,
        ),
    )

    await cursor.close()
    return int(cursor.lastrowid)


__all__ = ["append_audit_row", "record_job_error"]
