import aiosqlite

from dmguard.repo_common import fetch_one_dict


async def kv_get(
    connection: aiosqlite.Connection,
    key: str,
) -> str | None:
    row = await fetch_one_dict(
        connection,
        """
        SELECT value
        FROM kv_store
        WHERE key = ?
        """,
        (key,),
    )

    if row is None:
        return None

    return str(row["value"])


async def kv_set(
    connection: aiosqlite.Connection,
    *,
    key: str,
    value: str,
    updated_at: str,
) -> None:
    await connection.execute(
        """
        INSERT INTO kv_store (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
          value = excluded.value,
          updated_at = excluded.updated_at
        """,
        (key, value, updated_at),
    )


__all__ = ["kv_get", "kv_set"]
