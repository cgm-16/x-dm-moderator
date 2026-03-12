import pytest

from dmguard.job_machine import (
    JobStage,
    JobStatus,
    is_terminal,
    next_backoff_seconds,
    next_stage,
)


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (JobStage.fetch_dm, JobStage.download_media),
        (JobStage.download_media, JobStage.classify),
        (JobStage.classify, JobStage.block),
        (JobStage.block, None),
    ],
)
def test_next_stage_returns_expected_stage(
    current: JobStage, expected: JobStage | None
) -> None:
    assert next_stage(current) is expected


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [
        (1, 10),
        (2, 60),
        (3, 300),
    ],
)
def test_next_backoff_seconds_returns_expected_value(
    attempt: int, expected: int
) -> None:
    assert next_backoff_seconds(attempt) == expected


@pytest.mark.parametrize("attempt", [0, 4, 5])
def test_next_backoff_seconds_raises_after_max_retries(attempt: int) -> None:
    with pytest.raises(ValueError):
        next_backoff_seconds(attempt)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (JobStatus.queued, False),
        (JobStatus.processing, False),
        (JobStatus.done, True),
        (JobStatus.error, True),
        (JobStatus.skipped, True),
    ],
)
def test_is_terminal_returns_expected_value(status: JobStatus, expected: bool) -> None:
    assert is_terminal(status) is expected
