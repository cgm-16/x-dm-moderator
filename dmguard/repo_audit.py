import aiosqlite


async def append_audit_row(
    connection: aiosqlite.Connection,
    *,
    job_id: int,
    event_id: str,
    sender_id: str,
    outcome: str,
    policy: str,
    threshold: float,
    score: float | None,
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
          threshold,
          score,
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
            threshold,
            score,
            trigger_frame_index,
            trigger_time_sec,
            block_attempted,
        ),
    )

    await cursor.close()
    return int(cursor.lastrowid)


async def insert_job_error(
    connection: aiosqlite.Connection,
    *,
    job_id: int,
    stage: str | None,
    attempt: int | None,
    error_type: str | None,
    error_message: str | None,
    http_status: int | None,
) -> int:
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
        (job_id, stage, attempt, error_type, error_message, http_status),
    )

    await cursor.close()
    return int(cursor.lastrowid)


__all__ = ["append_audit_row", "insert_job_error"]
