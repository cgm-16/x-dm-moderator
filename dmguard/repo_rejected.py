import aiosqlite


async def insert_rejected_request(
    connection: aiosqlite.Connection,
    *,
    received_at: str,
    remote_ip: str | None = None,
    path: str | None = None,
    reason: str,
    body_sha256: str | None = None,
) -> int:
    cursor = await connection.execute(
        """
        INSERT INTO rejected_requests (
          received_at,
          remote_ip,
          path,
          reason,
          body_sha256
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (received_at, remote_ip, path, reason, body_sha256),
    )

    await cursor.close()
    return int(cursor.lastrowid)


__all__ = ["insert_rejected_request"]
