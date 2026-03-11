from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite


@asynccontextmanager
async def get_connection(db_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(str(db_path))

    try:
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA journal_mode = WAL")
        await connection.execute("PRAGMA busy_timeout = 5000")
        yield connection
    finally:
        await connection.close()


__all__ = ["get_connection"]
