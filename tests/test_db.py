import asyncio
from pathlib import Path


def run(coroutine):
    return asyncio.run(coroutine)


async def insert_and_read_value(db_path: Path) -> str:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        await connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        await connection.execute("INSERT INTO sample (value) VALUES ('ok')")
        await connection.commit()

    async with get_connection(db_path) as connection:
        cursor = await connection.execute("SELECT value FROM sample")
        row = await cursor.fetchone()

    return row[0]


async def fetch_pragma_value(db_path: Path, pragma_name: str):
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(f"PRAGMA {pragma_name}")
        return await cursor.fetchone()


def test_get_connection_opens_and_closes_cleanly(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    assert run(insert_and_read_value(db_path)) == "ok"


def test_get_connection_enables_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    pragma_row = run(fetch_pragma_value(db_path, "foreign_keys"))

    assert pragma_row == (1,)


def test_get_connection_uses_wal_journal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    pragma_row = run(fetch_pragma_value(db_path, "journal_mode"))

    assert pragma_row == ("wal",)


def test_get_connection_sets_busy_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    pragma_row = run(fetch_pragma_value(db_path, "busy_timeout"))

    assert pragma_row == (5000,)
