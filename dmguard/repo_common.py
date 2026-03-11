from collections.abc import Sequence

import aiosqlite


async def fetch_one_dict(
    connection: aiosqlite.Connection,
    query: str,
    params: Sequence[object] = (),
) -> dict[str, object] | None:
    cursor = await connection.execute(query, params)

    try:
        row = await cursor.fetchone()
        if row is None:
            return None

        return _row_to_dict(cursor, row)
    finally:
        await cursor.close()


async def fetch_all_dicts(
    connection: aiosqlite.Connection,
    query: str,
    params: Sequence[object] = (),
) -> list[dict[str, object]]:
    cursor = await connection.execute(query, params)

    try:
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, row) for row in rows]
    finally:
        await cursor.close()


def _row_to_dict(
    cursor: aiosqlite.Cursor,
    row: tuple[object, ...],
) -> dict[str, object]:
    columns = [description[0] for description in cursor.description or ()]
    return dict(zip(columns, row, strict=True))


__all__ = ["fetch_all_dicts", "fetch_one_dict"]
