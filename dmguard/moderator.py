import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Literal

import aiosqlite

from dmguard.classifier_contract import ClassifierResponse
from dmguard.classifier_runner import run_classifier
from dmguard.frame_extractor import FrameInfo, extract_frames
from dmguard.media_dispatch import dispatch_media
from dmguard.media_download import cleanup_media, download_media
from dmguard.repo_senders import get_allowed_sender, insert_allowed_sender
from dmguard.x_client import XClient
from dmguard.x_dm import DMEvent, fetch_dm_event


_LOGGER = logging.getLogger("dmguard")
_POLICY = "O2_violence_harm_cruelty"
_VIDEO_SUFFIXES = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}

ModerationResult = Literal[
    "blocked",
    "error",
    "safe",
    "skipped_allowlist",
    "text_only_logged",
]


@dataclass(frozen=True)
class ModerationOutcome:
    outcome: ModerationResult
    category_code: str | None = None
    rationale: str | None = None
    trigger_frame_index: int | None = None
    trigger_time_sec: float | None = None
    block_attempted: bool = False


async def moderate_job(
    job: Mapping[str, object],
    connection: aiosqlite.Connection,
    x_client: XClient,
    classifier_cmd: Sequence[str],
) -> ModerationOutcome:
    sender_id = _get_job_sender_id(job)

    if sender_id is not None:
        allowed_sender = await get_allowed_sender(connection, sender_id)
        if allowed_sender is not None:
            return ModerationOutcome(outcome="skipped_allowlist")

    event = await fetch_dm_event(x_client, str(job["event_id"]))
    media_items = dispatch_media(event)

    if not media_items:
        return ModerationOutcome(outcome="text_only_logged")

    downloaded_paths: list[Path] = []
    extracted_frame_paths: list[Path] = []
    safe_response: ClassifierResponse | None = None

    try:
        for media_item in media_items:
            downloaded_path = await download_media(x_client, media_item, event.event_id)
            downloaded_paths.append(downloaded_path)

            if _is_video_file(downloaded_path):
                frames = extract_frames(
                    downloaded_path,
                    f"{event.event_id}_{media_item.media_key}",
                )
                if not frames:
                    raise RuntimeError(
                        f"No classifier frames extracted for media item {media_item.media_key}"
                    )

                extracted_frame_paths.extend(frame.path for frame in frames)
                unsafe_outcome, frame_safe_response = await _classify_frames(
                    frames,
                    event,
                    x_client,
                    classifier_cmd,
                )
                if unsafe_outcome is not None:
                    return unsafe_outcome

                if safe_response is None and frame_safe_response is not None:
                    safe_response = frame_safe_response
                continue

            response = await _classify_path(downloaded_path, classifier_cmd)
            if _is_unsafe(response):
                return await _blocked_or_error_outcome(
                    event,
                    x_client,
                    category_code=response.category,
                    rationale=response.rationale,
                    trigger_frame_index=None,
                    trigger_time_sec=None,
                )

            if safe_response is None:
                safe_response = response
    finally:
        cleanup_media(extracted_frame_paths)
        cleanup_media(downloaded_paths)

    if safe_response is None:
        raise RuntimeError(f"No classifier inputs produced for event {event.event_id}")

    if await get_allowed_sender(connection, event.sender_id) is None:
        await insert_allowed_sender(
            connection,
            sender_id=event.sender_id,
            source_event_id=event.event_id,
        )
        await connection.commit()

    return ModerationOutcome(
        outcome="safe",
        category_code=safe_response.category,
        rationale=safe_response.rationale,
    )


async def _classify_frames(
    frames: list[FrameInfo],
    event: DMEvent,
    x_client: XClient,
    classifier_cmd: Sequence[str],
) -> tuple[ModerationOutcome | None, ClassifierResponse | None]:
    safe_response: ClassifierResponse | None = None

    for frame in frames:
        response = await _classify_path(frame.path, classifier_cmd)
        if _is_unsafe(response):
            return (
                await _blocked_or_error_outcome(
                    event,
                    x_client,
                    category_code=response.category,
                    rationale=response.rationale,
                    trigger_frame_index=frame.index,
                    trigger_time_sec=frame.time_sec,
                ),
                None,
            )

        if safe_response is None:
            safe_response = response

    return None, safe_response


async def _classify_path(
    path: Path,
    classifier_cmd: Sequence[str],
) -> ClassifierResponse:
    return await asyncio.to_thread(
        run_classifier,
        {
            "mode": "image",
            "files": [str(path)],
            "policy": _POLICY,
        },
        classifier_cmd,
    )


async def _blocked_or_error_outcome(
    event: DMEvent,
    x_client: XClient,
    *,
    category_code: str,
    rationale: str,
    trigger_frame_index: int | None,
    trigger_time_sec: float | None,
) -> ModerationOutcome:
    blocked = await _attempt_block_sender(event, x_client)
    outcome: ModerationResult = "blocked" if blocked else "error"
    return ModerationOutcome(
        outcome=outcome,
        category_code=category_code,
        rationale=rationale,
        trigger_frame_index=trigger_frame_index,
        trigger_time_sec=trigger_time_sec,
        block_attempted=True,
    )


async def _attempt_block_sender(event: DMEvent, x_client: XClient) -> bool:
    del x_client
    _LOGGER.warning(
        "Block sender placeholder is not implemented sender_id=%s event_id=%s",
        event.sender_id,
        event.event_id,
    )
    return False


def _get_job_sender_id(job: Mapping[str, object]) -> str | None:
    sender_id = job.get("sender_id")
    return sender_id if isinstance(sender_id, str) and sender_id else None


def _is_unsafe(response: ClassifierResponse) -> bool:
    return response.rating == "unsafe" and response.category.startswith("O2")


def _is_video_file(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_SUFFIXES


__all__ = ["ModerationOutcome", "moderate_job"]
