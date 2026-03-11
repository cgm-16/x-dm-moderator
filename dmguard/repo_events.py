import aiosqlite

from dmguard.repo_common import fetch_one_dict


async def insert_event(
    connection: aiosqlite.Connection,
    *,
    event_id: str,
    received_at: str,
    payload_json: str,
    sender_id: str | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO webhook_events (event_id, received_at, payload_json, sender_id)
        VALUES (?, ?, ?, ?)
        """,
        (event_id, received_at, payload_json, sender_id),
    )


async def get_event(
    connection: aiosqlite.Connection,
    event_id: str,
) -> dict[str, object] | None:
    return await fetch_one_dict(
        connection,
        """
        SELECT event_id, received_at, payload_json, sender_id
        FROM webhook_events
        WHERE event_id = ?
        """,
        (event_id,),
    )


__all__ = ["get_event", "insert_event"]
