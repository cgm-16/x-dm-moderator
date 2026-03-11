import asyncio
from pathlib import Path

import pytest


def run(coroutine):
    return asyncio.run(coroutine)


async def bootstrap_database(db_path: Path) -> None:
    from dmguard.db import get_connection
    from dmguard.schema import bootstrap_schema

    async with get_connection(db_path) as connection:
        await bootstrap_schema(connection)


async def count_rows(db_path: Path, table: str) -> int:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(f"SELECT COUNT(*) FROM {table}")

        try:
            row = await cursor.fetchone()
            assert row is not None
            return int(row[0])
        finally:
            await cursor.close()


class FakeCursor:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount

    async def close(self) -> None:
        return None


class LimitedVariableConnection:
    def __init__(self, *, max_variables: int) -> None:
        self.max_variables = max_variables
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(
        self,
        query: str,
        params: tuple[object, ...] | list[object],
    ) -> FakeCursor:
        normalized_params = tuple(params)
        self.calls.append((query, normalized_params))

        if len(normalized_params) > self.max_variables:
            raise RuntimeError("too many SQL variables")

        rowcount = len(normalized_params)
        if "DELETE FROM webhook_events" in query:
            rowcount -= 1

        return FakeCursor(rowcount=rowcount)


def test_prune_old_data_deletes_old_terminal_history_in_order(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    async def scenario():
        from dmguard.db import get_connection
        from dmguard.job_machine import JobStage, JobStatus
        from dmguard.repo_audit import append_audit_row, insert_job_error
        from dmguard.repo_events import insert_event
        from dmguard.repo_jobs import insert_job, update_job_status
        from dmguard.repo_rejected import insert_rejected_request
        from dmguard.pruner import PruneResult, prune_old_data

        async with get_connection(db_path) as connection:
            await insert_event(
                connection,
                event_id="event-old",
                received_at="2000-01-01 00:00:00",
                payload_json='{"event_id":"event-old"}',
                sender_id="sender-old",
            )
            job_id = await insert_job(
                connection,
                event_id="event-old",
                status=JobStatus.queued,
                stage=JobStage.fetch_dm,
                next_run_at="2000-01-01 00:00:00",
                sender_id="sender-old",
            )
            await update_job_status(
                connection,
                job_id,
                status=JobStatus.done,
                stage=JobStage.fetch_dm,
            )
            await connection.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
                ("2000-01-01 00:00:00", job_id),
            )

            error_id = await insert_job_error(
                connection,
                job_id=job_id,
                stage=JobStage.fetch_dm.value,
                attempt=1,
                error_type="network",
                error_message="boom",
                http_status=500,
            )
            await connection.execute(
                "UPDATE job_errors SET created_at = ? WHERE id = ?",
                ("2000-01-01 00:00:00", error_id),
            )

            audit_id = await append_audit_row(
                connection,
                job_id=job_id,
                event_id="event-old",
                sender_id="sender-old",
                outcome="safe",
                policy="violence_gore",
                threshold=0.9,
                score=0.01,
                trigger_frame_index=None,
                trigger_time_sec=None,
                block_attempted=False,
            )
            await connection.execute(
                "UPDATE moderation_audit SET created_at = ? WHERE id = ?",
                ("2000-01-01 00:00:00", audit_id),
            )

            rejected_id = await insert_rejected_request(
                connection,
                received_at="2000-01-01 00:00:00",
                remote_ip="127.0.0.1",
                path="/webhooks/x",
                reason="invalid_json",
                body_sha256="abc123",
            )
            await connection.execute(
                """
                CREATE TRIGGER jobs_require_job_errors_pruned
                BEFORE DELETE ON jobs
                WHEN EXISTS (
                  SELECT 1
                  FROM job_errors
                  WHERE job_errors.job_id = OLD.job_id
                )
                BEGIN
                  SELECT RAISE(ABORT, 'job_errors must be deleted before jobs');
                END
                """
            )
            await connection.execute(
                """
                CREATE TRIGGER events_require_jobs_pruned
                BEFORE DELETE ON webhook_events
                WHEN EXISTS (
                  SELECT 1
                  FROM jobs
                  WHERE jobs.event_id = OLD.event_id
                )
                BEGIN
                  SELECT RAISE(ABORT, 'jobs must be deleted before webhook_events');
                END
                """
            )

            result = await prune_old_data(connection)
            await connection.commit()

            return result, PruneResult, rejected_id

    result, prune_result_type, rejected_id = run(scenario())

    assert result == prune_result_type(
        job_errors_deleted=1,
        jobs_deleted=1,
        webhook_events_deleted=1,
        moderation_audit_deleted=1,
        rejected_requests_deleted=1,
    )
    assert rejected_id > 0
    assert run(count_rows(db_path, "job_errors")) == 0
    assert run(count_rows(db_path, "jobs")) == 0
    assert run(count_rows(db_path, "webhook_events")) == 0
    assert run(count_rows(db_path, "moderation_audit")) == 0
    assert run(count_rows(db_path, "rejected_requests")) == 0


def test_prune_old_data_preserves_non_terminal_jobs_and_sender_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    async def scenario():
        from dmguard.db import get_connection
        from dmguard.job_machine import JobStage, JobStatus
        from dmguard.repo_events import insert_event
        from dmguard.repo_jobs import insert_job
        from dmguard.repo_senders import (
            insert_allowed_sender,
            insert_blocked_sender,
            upsert_block_failed_sender,
        )
        from dmguard.pruner import PruneResult, prune_old_data

        async with get_connection(db_path) as connection:
            await insert_event(
                connection,
                event_id="event-queued",
                received_at="2000-01-01 00:00:00",
                payload_json='{"event_id":"event-queued"}',
                sender_id="sender-queued",
            )
            queued_job_id = await insert_job(
                connection,
                event_id="event-queued",
                status=JobStatus.queued,
                stage=JobStage.fetch_dm,
                next_run_at="2000-01-01 00:00:00",
                sender_id="sender-queued",
            )
            await connection.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
                ("2000-01-01 00:00:00", queued_job_id),
            )

            await insert_event(
                connection,
                event_id="event-processing",
                received_at="2000-01-01 00:00:00",
                payload_json='{"event_id":"event-processing"}',
                sender_id="sender-processing",
            )
            processing_job_id = await insert_job(
                connection,
                event_id="event-processing",
                status=JobStatus.processing,
                stage=JobStage.fetch_dm,
                next_run_at="2000-01-01 00:00:00",
                processing_started_at="2000-01-01 00:00:00",
                sender_id="sender-processing",
            )
            await connection.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
                ("2000-01-01 00:00:00", processing_job_id),
            )

            await insert_allowed_sender(
                connection,
                sender_id="allowed-1",
                source_event_id="event-queued",
            )
            await connection.execute(
                "UPDATE allowed_senders SET created_at = ? WHERE sender_id = ?",
                ("2000-01-01 00:00:00", "allowed-1"),
            )

            await insert_blocked_sender(
                connection,
                sender_id="blocked-1",
                source_event_id="event-processing",
            )
            await connection.execute(
                "UPDATE blocked_senders SET created_at = ? WHERE sender_id = ?",
                ("2000-01-01 00:00:00", "blocked-1"),
            )

            await upsert_block_failed_sender(
                connection,
                sender_id="failed-1",
                next_retry_at="2000-01-01 00:00:00",
                first_failed_at="2000-01-01 00:00:00",
                last_failed_at="2000-01-01 00:00:00",
            )

            result = await prune_old_data(connection)
            await connection.commit()

            queued_count = await count_rows(db_path, "jobs")
            allowed_count = await count_rows(db_path, "allowed_senders")
            blocked_count = await count_rows(db_path, "blocked_senders")
            failed_count = await count_rows(db_path, "block_failed_senders")
            event_count = await count_rows(db_path, "webhook_events")

            return (
                result,
                PruneResult,
                queued_count,
                allowed_count,
                blocked_count,
                failed_count,
                event_count,
            )

    (
        result,
        prune_result_type,
        job_count,
        allowed_count,
        blocked_count,
        failed_count,
        event_count,
    ) = run(scenario())

    assert result == prune_result_type(
        job_errors_deleted=0,
        jobs_deleted=0,
        webhook_events_deleted=0,
        moderation_audit_deleted=0,
        rejected_requests_deleted=0,
    )
    assert job_count == 2
    assert allowed_count == 1
    assert blocked_count == 1
    assert failed_count == 1
    assert event_count == 2


def test_prune_old_data_keeps_recent_terminal_history(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    async def scenario():
        from dmguard.db import get_connection
        from dmguard.job_machine import JobStage, JobStatus
        from dmguard.repo_audit import append_audit_row, insert_job_error
        from dmguard.repo_events import insert_event
        from dmguard.repo_jobs import insert_job, update_job_status
        from dmguard.pruner import PruneResult, prune_old_data

        async with get_connection(db_path) as connection:
            await insert_event(
                connection,
                event_id="event-recent",
                received_at="2026-03-11 00:00:00",
                payload_json='{"event_id":"event-recent"}',
                sender_id="sender-recent",
            )
            job_id = await insert_job(
                connection,
                event_id="event-recent",
                status=JobStatus.queued,
                stage=JobStage.fetch_dm,
                next_run_at="2026-03-11 00:00:00",
                sender_id="sender-recent",
            )
            await update_job_status(
                connection,
                job_id,
                status=JobStatus.error,
                stage=JobStage.fetch_dm,
            )
            await insert_job_error(
                connection,
                job_id=job_id,
                stage=JobStage.fetch_dm.value,
                attempt=1,
                error_type="network",
                error_message="boom",
                http_status=500,
            )
            await append_audit_row(
                connection,
                job_id=job_id,
                event_id="event-recent",
                sender_id="sender-recent",
                outcome="error",
                policy="violence_gore",
                threshold=0.9,
                score=None,
                trigger_frame_index=None,
                trigger_time_sec=None,
                block_attempted=False,
            )

            result = await prune_old_data(connection)
            await connection.commit()

            return result, PruneResult

    result, prune_result_type = run(scenario())

    assert result == prune_result_type(
        job_errors_deleted=0,
        jobs_deleted=0,
        webhook_events_deleted=0,
        moderation_audit_deleted=0,
        rejected_requests_deleted=0,
    )
    assert run(count_rows(db_path, "job_errors")) == 1
    assert run(count_rows(db_path, "jobs")) == 1
    assert run(count_rows(db_path, "webhook_events")) == 1
    assert run(count_rows(db_path, "moderation_audit")) == 1


def test_prune_old_data_deletes_old_skipped_jobs(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    run(bootstrap_database(db_path))

    async def scenario():
        from dmguard.db import get_connection
        from dmguard.job_machine import JobStage, JobStatus
        from dmguard.pruner import PruneResult, prune_old_data
        from dmguard.repo_events import insert_event
        from dmguard.repo_jobs import insert_job, update_job_status

        async with get_connection(db_path) as connection:
            await insert_event(
                connection,
                event_id="event-skipped",
                received_at="2000-01-01 00:00:00",
                payload_json='{"event_id":"event-skipped"}',
                sender_id="sender-skipped",
            )
            job_id = await insert_job(
                connection,
                event_id="event-skipped",
                status=JobStatus.queued,
                stage=JobStage.fetch_dm,
                next_run_at="2000-01-01 00:00:00",
                sender_id="sender-skipped",
            )
            await update_job_status(
                connection,
                job_id,
                status=JobStatus.skipped,
                stage=JobStage.fetch_dm,
            )
            await connection.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
                ("2000-01-01 00:00:00", job_id),
            )

            result = await prune_old_data(connection)
            await connection.commit()

            return result, PruneResult

    result, prune_result_type = run(scenario())

    assert result == prune_result_type(
        job_errors_deleted=0,
        jobs_deleted=1,
        webhook_events_deleted=1,
        moderation_audit_deleted=0,
        rejected_requests_deleted=0,
    )
    assert run(count_rows(db_path, "jobs")) == 0
    assert run(count_rows(db_path, "webhook_events")) == 0


def test_delete_by_ids_chunks_large_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    from dmguard import pruner

    monkeypatch.setattr(pruner, "_SQLITE_MAX_VARIABLES", 3, raising=False)
    connection = LimitedVariableConnection(max_variables=3)

    deleted = run(
        pruner._delete_by_ids(
            connection,
            table="jobs",
            column="job_id",
            values=[1, 2, 3, 4, 5, 6, 7],
        )
    )

    assert deleted == 7
    assert [params for _, params in connection.calls] == [
        (1, 2, 3),
        (4, 5, 6),
        (7,),
    ]


def test_delete_pruned_webhook_events_chunks_large_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard import pruner

    monkeypatch.setattr(pruner, "_SQLITE_MAX_VARIABLES", 4, raising=False)
    connection = LimitedVariableConnection(max_variables=4)

    deleted = run(
        pruner._delete_pruned_webhook_events(
            connection,
            event_ids=["event-1", "event-2", "event-3", "event-4", "event-5"],
            cutoff_modifier="-30 days",
        )
    )

    assert deleted == 5
    assert [params for _, params in connection.calls] == [
        ("event-1", "event-2", "event-3", "-30 days"),
        ("event-4", "event-5", "-30 days"),
    ]
