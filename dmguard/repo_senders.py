import aiosqlite

from dmguard.repo_common import _UNCHANGED, fetch_one_dict


async def insert_allowed_sender(
    connection: aiosqlite.Connection,
    *,
    sender_id: str,
    source_event_id: str,
) -> None:
    cursor = await connection.execute(
        """
        INSERT INTO allowed_senders (sender_id, source_event_id)
        VALUES (?, ?)
        """,
        (sender_id, source_event_id),
    )
    await cursor.close()


async def get_allowed_sender(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> dict[str, object] | None:
    return await fetch_one_dict(
        connection,
        """
        SELECT sender_id, created_at, source_event_id
        FROM allowed_senders
        WHERE sender_id = ?
        """,
        (sender_id,),
    )


async def delete_allowed_sender(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> None:
    cursor = await connection.execute(
        """
        DELETE FROM allowed_senders
        WHERE sender_id = ?
        """,
        (sender_id,),
    )
    await cursor.close()


async def insert_blocked_sender(
    connection: aiosqlite.Connection,
    *,
    sender_id: str,
    source_event_id: str | None = None,
) -> None:
    cursor = await connection.execute(
        """
        INSERT INTO blocked_senders (sender_id, source_event_id)
        VALUES (?, ?)
        """,
        (sender_id, source_event_id),
    )
    await cursor.close()


async def get_blocked_sender(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> dict[str, object] | None:
    return await fetch_one_dict(
        connection,
        """
        SELECT sender_id, created_at, source_event_id
        FROM blocked_senders
        WHERE sender_id = ?
        """,
        (sender_id,),
    )


async def delete_blocked_sender(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> None:
    cursor = await connection.execute(
        """
        DELETE FROM blocked_senders
        WHERE sender_id = ?
        """,
        (sender_id,),
    )
    await cursor.close()


async def upsert_block_failed_sender(
    connection: aiosqlite.Connection,
    *,
    sender_id: str,
    next_retry_at: str,
    fail_count: int = 1,
    first_failed_at: str | None | object = _UNCHANGED,
    last_failed_at: str | None | object = _UNCHANGED,
) -> None:
    insert_first_failed_at = None if first_failed_at is _UNCHANGED else first_failed_at
    insert_last_failed_at = None if last_failed_at is _UNCHANGED else last_failed_at

    cursor = await connection.execute(
        """
        INSERT INTO block_failed_senders (
          sender_id,
          first_failed_at,
          last_failed_at,
          next_retry_at,
          fail_count
        )
        VALUES (
          ?,
          COALESCE(?, datetime('now')),
          COALESCE(?, datetime('now')),
          ?,
          ?
        )
        ON CONFLICT(sender_id) DO UPDATE SET
          first_failed_at = block_failed_senders.first_failed_at,
          last_failed_at = COALESCE(excluded.last_failed_at, block_failed_senders.last_failed_at),
          next_retry_at = excluded.next_retry_at,
          fail_count = excluded.fail_count
        """,
        (
            sender_id,
            insert_first_failed_at,
            insert_last_failed_at,
            next_retry_at,
            fail_count,
        ),
    )
    await cursor.close()


async def get_block_failed_sender(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> dict[str, object] | None:
    return await fetch_one_dict(
        connection,
        """
        SELECT sender_id, first_failed_at, last_failed_at, next_retry_at, fail_count
        FROM block_failed_senders
        WHERE sender_id = ?
        """,
        (sender_id,),
    )


async def delete_block_failed_sender(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> None:
    cursor = await connection.execute(
        """
        DELETE FROM block_failed_senders
        WHERE sender_id = ?
        """,
        (sender_id,),
    )
    await cursor.close()


__all__ = [
    "delete_allowed_sender",
    "delete_block_failed_sender",
    "delete_blocked_sender",
    "get_allowed_sender",
    "get_block_failed_sender",
    "get_blocked_sender",
    "insert_allowed_sender",
    "insert_blocked_sender",
    "upsert_block_failed_sender",
]
