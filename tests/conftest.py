import asyncio
import base64
import hashlib
import hmac
import logging
import os
from pathlib import Path
import sys
from tempfile import gettempdir

if not sys.platform.startswith("win"):
    # Keep pytest collection self-contained when dmguard.paths fails fast on non-Windows.
    # Must run before any dmguard import (secrets.py imports paths at the top level).
    os.environ.setdefault(
        "DMGUARD_APP_ROOT",
        str(Path(gettempdir()) / "dmguard-test-app"),
    )
    os.environ.setdefault(
        "DMGUARD_DATA_ROOT",
        str(Path(gettempdir()) / "dmguard-test-data"),
    )

from dmguard.job_machine import JobStage, JobStatus
from dmguard.secrets import SecretStore

# Shared test helpers — check here before writing a new one in a test file.


class StubSecretStore(SecretStore):
    """In-memory secret store for tests. Accepts arbitrary key-value pairs."""

    def __init__(self, **secrets: str) -> None:
        self._secrets = secrets

    def get(self, key: str) -> str:
        try:
            return self._secrets[key]
        except KeyError:
            raise AssertionError(f"Unexpected secret key: {key}") from None

    def update(self, key: str, value: str) -> None:
        self._secrets[key] = value


def run(coroutine):
    return asyncio.run(coroutine)


async def bootstrap_database(db_path: Path) -> None:
    from dmguard.db import get_connection
    from dmguard.schema import bootstrap_schema

    async with get_connection(db_path) as connection:
        await bootstrap_schema(connection)


async def insert_event_row(
    db_path: Path,
    *,
    event_id: str,
    sender_id: str | None = None,
) -> None:
    from dmguard.db import get_connection
    from dmguard.repo_events import insert_event

    async with get_connection(db_path) as connection:
        await insert_event(
            connection,
            event_id=event_id,
            received_at="2026-03-11T00:00:00Z",
            payload_json='{"event_id":"%s"}' % event_id,
            sender_id=sender_id,
        )
        await connection.commit()


async def insert_job_row(
    db_path: Path,
    *,
    event_id: str,
    next_run_at: str,
    status: JobStatus = JobStatus.queued,
    stage: JobStage = JobStage.fetch_dm,
    attempt: int = 0,
    processing_started_at: str | None = None,
) -> int:
    from dmguard.db import get_connection
    from dmguard.repo_jobs import insert_job

    async with get_connection(db_path) as connection:
        job_id = await insert_job(
            connection,
            event_id=event_id,
            status=status,
            stage=stage,
            next_run_at=next_run_at,
            attempt=attempt,
            processing_started_at=processing_started_at,
        )
        await connection.commit()

    return job_id


def build_signature(raw_body: bytes, consumer_secret: str) -> str:
    digest = hmac.new(
        consumer_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    encoded = base64.b64encode(digest).decode("ascii")
    return f"sha256={encoded}"


def clear_logger(name: str) -> None:
    logger = logging.getLogger(name)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(logging.NOTSET)
    logger.propagate = True
