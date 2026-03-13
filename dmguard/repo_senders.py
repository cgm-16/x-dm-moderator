from datetime import datetime, timedelta, timezone

import aiosqlite

from dmguard.repo_common import _UNCHANGED, fetch_one_dict

_BLOCK_RETRY_COOLDOWN = timedelta(hours=24)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _parse_utc(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _format_utc(timestamp: datetime) -> str:
    return (
        timestamp.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


async def add_to_allowlist(
    connection: aiosqlite.Connection,
    *,
    sender_id: str,
    source_event_id: str,
) -> None:
    await insert_allowed_sender(
        connection,
        sender_id=sender_id,
        source_event_id=source_event_id,
    )


async def is_allowlisted(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> bool:
    return await get_allowed_sender(connection, sender_id) is not None


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


async def record_block_success(
    connection: aiosqlite.Connection,
    *,
    sender_id: str,
    source_event_id: str | None = None,
) -> None:
    cursor = await connection.execute(
        """
        INSERT INTO blocked_senders (sender_id, source_event_id)
        VALUES (?, ?)
        ON CONFLICT(sender_id) DO UPDATE SET
          source_event_id = excluded.source_event_id
        """,
        (sender_id, source_event_id),
    )
    await cursor.close()
    await delete_block_failed_sender(connection, sender_id)


async def is_blocked(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> bool:
    return await get_blocked_sender(connection, sender_id) is not None


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


async def record_block_failure(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> None:
    now = _utc_now()
    next_retry_at = _format_utc(_parse_utc(now) + _BLOCK_RETRY_COOLDOWN)
    existing_row = await get_block_failed_sender(connection, sender_id)

    if existing_row is None:
        await upsert_block_failed_sender(
            connection,
            sender_id=sender_id,
            next_retry_at=next_retry_at,
            fail_count=1,
            first_failed_at=now,
            last_failed_at=now,
        )
        return

    await upsert_block_failed_sender(
        connection,
        sender_id=sender_id,
        next_retry_at=next_retry_at,
        fail_count=int(existing_row["fail_count"]) + 1,
        first_failed_at=existing_row["first_failed_at"],
        last_failed_at=now,
    )


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


async def get_block_failed(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> dict[str, object] | None:
    return await get_block_failed_sender(connection, sender_id)


async def is_block_on_cooldown(
    connection: aiosqlite.Connection,
    sender_id: str,
) -> bool:
    block_failed_sender = await get_block_failed(connection, sender_id)
    if block_failed_sender is None:
        return False

    return _parse_utc(str(block_failed_sender["next_retry_at"])) > _parse_utc(
        _utc_now()
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
    "add_to_allowlist",
    "delete_allowed_sender",
    "delete_block_failed_sender",
    "delete_blocked_sender",
    "get_block_failed",
    "get_allowed_sender",
    "get_block_failed_sender",
    "get_blocked_sender",
    "is_allowlisted",
    "is_block_on_cooldown",
    "is_blocked",
    "insert_allowed_sender",
    "insert_blocked_sender",
    "record_block_failure",
    "record_block_success",
    "upsert_block_failed_sender",
]
