import aiosqlite

from dmguard.job_machine import JobStage, JobStatus


def _enum_values_sql(enum_type: type[JobStatus] | type[JobStage]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS webhook_events (
      event_id TEXT PRIMARY KEY,
      received_at TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      sender_id TEXT
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS jobs (
      job_id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_id TEXT NOT NULL,
      status TEXT NOT NULL,
      stage TEXT NOT NULL,
      attempt INTEGER NOT NULL DEFAULT 0,
      next_run_at TEXT NOT NULL,
      processing_started_at TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      sender_id TEXT,
      FOREIGN KEY (event_id) REFERENCES webhook_events(event_id) ON DELETE CASCADE,
      CHECK (status IN ({_enum_values_sql(JobStatus)})),
      CHECK (stage IN ({_enum_values_sql(JobStage)}))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_errors (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER NOT NULL,
      stage TEXT,
      attempt INTEGER,
      error_type TEXT,
      error_message TEXT,
      http_status INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rejected_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      received_at TEXT NOT NULL DEFAULT (datetime('now')),
      remote_ip TEXT,
      path TEXT,
      reason TEXT NOT NULL,
      body_sha256 TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS allowed_senders (
      sender_id TEXT PRIMARY KEY,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      source_event_id TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blocked_senders (
      sender_id TEXT PRIMARY KEY,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      source_event_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS block_failed_senders (
      sender_id TEXT PRIMARY KEY,
      first_failed_at TEXT NOT NULL DEFAULT (datetime('now')),
      last_failed_at TEXT NOT NULL DEFAULT (datetime('now')),
      next_retry_at TEXT NOT NULL,
      fail_count INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS moderation_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER NOT NULL,
      event_id TEXT NOT NULL,
      sender_id TEXT NOT NULL,
      outcome TEXT NOT NULL,
      policy TEXT NOT NULL,
      threshold REAL NOT NULL,
      score REAL,
      trigger_frame_index INTEGER,
      trigger_time_sec REAL,
      block_attempted INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      CHECK (outcome IN ('safe', 'blocked', 'skipped_allowlist', 'text_only_logged', 'error'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kv_store (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_event_id
    ON jobs(event_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_jobs_next_run_at
    ON jobs(status, next_run_at, job_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_moderation_audit_created_at
    ON moderation_audit(created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_webhook_events_received_at
    ON webhook_events(received_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_job_errors_job_id_created_at
    ON job_errors(job_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_rejected_requests_received_at
    ON rejected_requests(received_at)
    """,
)


async def bootstrap_schema(connection: aiosqlite.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        await connection.execute(statement)

    await connection.commit()


__all__ = ["bootstrap_schema"]
