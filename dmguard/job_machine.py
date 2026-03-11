from enum import Enum


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    done = "done"
    error = "error"
    skipped = "skipped"


class JobStage(str, Enum):
    fetch_dm = "fetch_dm"
    download_media = "download_media"
    classify = "classify"
    block = "block"


_NEXT_STAGE = {
    JobStage.fetch_dm: JobStage.download_media,
    JobStage.download_media: JobStage.classify,
    JobStage.classify: JobStage.block,
}

_BACKOFF_SECONDS = {
    0: 10,
    1: 60,
    2: 300,
}

_TERMINAL_STATUSES = {
    JobStatus.done,
    JobStatus.error,
    JobStatus.skipped,
}


def next_stage(current: JobStage) -> JobStage | None:
    return _NEXT_STAGE.get(current)


def next_backoff_seconds(attempt: int) -> int:
    try:
        return _BACKOFF_SECONDS[attempt]
    except KeyError as exc:
        raise ValueError(f"max retries exceeded for attempt {attempt}") from exc


def is_terminal(status: JobStatus) -> bool:
    return status in _TERMINAL_STATUSES
