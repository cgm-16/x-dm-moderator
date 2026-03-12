import sqlite3
from pathlib import Path

import pytest

from tests.conftest import bootstrap_database, run


EXPECTED_TABLES = {
    "allowed_senders",
    "block_failed_senders",
    "blocked_senders",
    "job_errors",
    "jobs",
    "kv_store",
    "moderation_audit",
    "rejected_requests",
    "webhook_events",
}

EXPECTED_INDEX_COLUMNS = {
    "jobs": {
        "idx_jobs_next_run_at": ["status", "next_run_at", "job_id"],
        "uq_jobs_event_id": ["event_id"],
    },
    "job_errors": {
        "idx_job_errors_job_id_created_at": ["job_id", "created_at"],
    },
    "moderation_audit": {
        "idx_moderation_audit_created_at": ["created_at"],
    },
    "rejected_requests": {
        "idx_rejected_requests_received_at": ["received_at"],
    },
    "webhook_events": {
        "idx_webhook_events_received_at": ["received_at"],
    },
}


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


async def bootstrap_schema_twice(db_path: Path) -> set[str]:
    from dmguard.db import get_connection
    from dmguard.schema import bootstrap_schema

    async with get_connection(db_path) as connection:
        await bootstrap_schema(connection)
        await bootstrap_schema(connection)

    return await fetch_table_names(db_path)


async def fetch_table_names(db_path: Path) -> set[str]:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        rows = await cursor.fetchall()

    return {row[0] for row in rows}


async def fetch_index_columns(db_path: Path, table_name: str) -> dict[str, list[str]]:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(f"PRAGMA index_list({table_name})")
        indexes = await cursor.fetchall()

        index_columns = {}
        for _, index_name, *_ in indexes:
            cursor = await connection.execute(f"PRAGMA index_info({index_name})")
            columns = await cursor.fetchall()
            index_columns[index_name] = [column[2] for column in columns]

    return index_columns


async def insert_job_without_matching_event(db_path: Path) -> None:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        await connection.execute(
            """
            INSERT INTO jobs (event_id, status, stage, next_run_at)
            VALUES (?, ?, ?, ?)
            """,
            ("missing-event", "queued", "fetch_dm", "2026-03-11T00:00:00Z"),
        )
        await connection.commit()


async def insert_job_with_invalid_status(db_path: Path) -> None:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        await connection.execute(
            """
            INSERT INTO webhook_events (event_id, received_at, payload_json, sender_id)
            VALUES (?, ?, ?, ?)
            """,
            (
                "event-1",
                "2026-03-11T00:00:00Z",
                "{}",
                "sender-1",
            ),
        )
        await connection.execute(
            """
            INSERT INTO jobs (event_id, status, stage, next_run_at)
            VALUES (?, ?, ?, ?)
            """,
            ("event-1", "not-a-status", "fetch_dm", "2026-03-11T00:00:00Z"),
        )
        await connection.commit()


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


def test_bootstrap_schema_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    table_names = run(bootstrap_schema_twice(db_path))

    assert table_names == EXPECTED_TABLES


def test_bootstrap_schema_creates_all_expected_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    for table_name, expected_indexes in EXPECTED_INDEX_COLUMNS.items():
        index_columns = run(fetch_index_columns(db_path, table_name))

        for index_name, expected_columns in expected_indexes.items():
            assert index_columns[index_name] == expected_columns


def test_bootstrap_schema_enforces_job_event_foreign_key(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    with pytest.raises(sqlite3.IntegrityError):
        run(insert_job_without_matching_event(db_path))


def test_bootstrap_schema_enforces_job_status_check(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    with pytest.raises(sqlite3.IntegrityError):
        run(insert_job_with_invalid_status(db_path))
