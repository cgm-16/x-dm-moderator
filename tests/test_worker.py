import asyncio
from contextlib import suppress
from pathlib import Path

import pytest

from dmguard.job_machine import JobStatus
from tests.conftest import bootstrap_database, insert_event_row, insert_job_row, run


async def fetch_job(db_path: Path, job_id: int) -> dict[str, object] | None:
    from dmguard.db import get_connection
    from dmguard.repo_jobs import get_job

    async with get_connection(db_path) as connection:
        return await get_job(connection, job_id)


async def wait_for_job_status(
    db_path: Path,
    job_id: int,
    expected_status: str,
) -> dict[str, object]:
    for _ in range(100):
        job = await fetch_job(db_path, job_id)
        if job is not None and job["status"] == expected_status:
            return job
        await asyncio.sleep(0.01)

    raise AssertionError(f"job {job_id} did not reach status {expected_status}")


def test_worker_loop_processes_a_queued_job(tmp_path: Path) -> None:
    from dmguard.worker import worker_loop

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T00:00:00Z",
        )
    )

    dispatched_jobs: list[dict[str, object]] = []

    async def scenario() -> None:
        dispatch_called = asyncio.Event()

        async def dispatch_fn(job: dict[str, object]) -> None:
            dispatched_jobs.append(job)
            dispatch_called.set()

        task = asyncio.create_task(
            worker_loop(
                db_path,
                dispatch_fn,
                poll_interval_seconds=0.01,
            )
        )

        try:
            await asyncio.wait_for(dispatch_called.wait(), timeout=1)
            await wait_for_job_status(db_path, job_id, JobStatus.done.value)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    run(scenario())
    job = run(fetch_job(db_path, job_id))

    assert dispatched_jobs
    assert dispatched_jobs[0]["job_id"] == job_id
    assert job is not None
    assert job["status"] == JobStatus.done.value


def test_worker_loop_requeues_job_after_dispatch_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard import scheduler
    from dmguard.worker import worker_loop

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    run(insert_event_row(db_path, event_id="event-1"))
    job_id = run(
        insert_job_row(
            db_path,
            event_id="event-1",
            next_run_at="2026-03-11T00:00:00Z",
        )
    )
    monkeypatch.setattr(scheduler, "_utc_now", lambda: "2026-03-11T10:00:00Z")

    async def scenario() -> None:
        dispatch_called = asyncio.Event()

        async def dispatch_fn(_: dict[str, object]) -> None:
            dispatch_called.set()
            raise RuntimeError("boom")

        task = asyncio.create_task(
            worker_loop(
                db_path,
                dispatch_fn,
                poll_interval_seconds=0.01,
            )
        )

        try:
            await asyncio.wait_for(dispatch_called.wait(), timeout=1)
            await wait_for_job_status(db_path, job_id, JobStatus.queued.value)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    run(scenario())
    job = run(fetch_job(db_path, job_id))

    assert job is not None
    assert job["status"] == JobStatus.queued.value
    assert job["attempt"] == 1
    assert job["next_run_at"] == "2026-03-11T10:00:10Z"
    assert job["processing_started_at"] is None


def test_worker_loop_stops_cleanly_on_cancellation(tmp_path: Path) -> None:
    from dmguard.worker import worker_loop

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))

    async def dispatch_fn(_: dict[str, object]) -> None:
        raise AssertionError("dispatch should not be called without queued jobs")

    async def scenario() -> None:
        task = asyncio.create_task(
            worker_loop(
                db_path,
                dispatch_fn,
                poll_interval_seconds=10,
            )
        )

        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
