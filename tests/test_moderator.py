from pathlib import Path

import pytest

from dmguard.classifier_contract import ClassifierResponse
from dmguard.frame_extractor import FrameInfo
from dmguard.x_dm import DMEvent, MediaItem
from tests.conftest import bootstrap_database, run


def build_job(
    *,
    job_id: int = 1,
    event_id: str = "event-1",
    sender_id: str | None = "sender-1",
) -> dict[str, object]:
    return {
        "job_id": job_id,
        "event_id": event_id,
        "sender_id": sender_id,
    }


def build_event(*media_items: MediaItem, sender_id: str = "sender-1") -> DMEvent:
    return DMEvent(
        event_id="event-1",
        sender_id=sender_id,
        text="hello world",
        created_at="2026-03-13T00:00:00.000Z",
        media_items=list(media_items),
    )


def build_response(
    *,
    rating: str,
    category: str,
    rationale: str,
) -> ClassifierResponse:
    return ClassifierResponse(
        policy="O2_violence_harm_cruelty",
        rating=rating,
        category=category,
        rationale=rationale,
        trigger_frame_index=None,
    )


def test_moderate_job_skips_allowlisted_sender_without_dm_lookup(
    tmp_path: Path,
) -> None:
    import dmguard.moderator as moderator

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))

    async def fake_fetch_dm_event(*_args, **_kwargs) -> DMEvent:
        raise AssertionError("DM lookup should not happen for allowlisted senders")

    async def scenario() -> moderator.ModerationOutcome:
        from dmguard.db import get_connection
        from dmguard.repo_senders import insert_allowed_sender

        async with get_connection(db_path) as connection:
            await insert_allowed_sender(
                connection,
                sender_id="sender-1",
                source_event_id="prior-event",
            )
            await connection.commit()
            return await moderator.moderate_job(
                build_job(),
                connection,
                object(),
                ["classifier-fake"],
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(moderator, "fetch_dm_event", fake_fetch_dm_event)
    try:
        outcome = run(scenario())
    finally:
        monkeypatch.undo()

    assert outcome.outcome == "skipped_allowlist"
    assert outcome.category_code is None
    assert outcome.rationale is None
    assert outcome.block_attempted is False


def test_moderate_job_returns_text_only_when_dm_has_no_media(tmp_path: Path) -> None:
    import dmguard.moderator as moderator

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))

    async def fake_fetch_dm_event(*_args, **_kwargs) -> DMEvent:
        return build_event()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(moderator, "fetch_dm_event", fake_fetch_dm_event)
    try:

        async def scenario() -> moderator.ModerationOutcome:
            from dmguard.db import get_connection

            async with get_connection(db_path) as connection:
                return await moderator.moderate_job(
                    build_job(),
                    connection,
                    object(),
                    ["classifier-fake"],
                )

        outcome = run(scenario())
    finally:
        monkeypatch.undo()

    assert outcome.outcome == "text_only_logged"
    assert outcome.category_code is None
    assert outcome.rationale is None


def test_moderate_job_marks_safe_media_and_adds_sender_to_allowlist(
    tmp_path: Path,
) -> None:
    import dmguard.moderator as moderator

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    download_path = tmp_path / "downloaded-photo.jpg"

    photo = MediaItem(
        media_key="3_1",
        type="photo",
        url="https://example.com/photo.jpg",
    )

    async def fake_fetch_dm_event(*_args, **_kwargs) -> DMEvent:
        return build_event(photo)

    async def fake_download_media(*_args, **_kwargs) -> Path:
        download_path.write_bytes(b"photo-bytes")
        return download_path

    def fake_run_classifier(*_args, **_kwargs) -> ClassifierResponse:
        return build_response(
            rating="safe",
            category="NA: None applying",
            rationale="No violence found",
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(moderator, "fetch_dm_event", fake_fetch_dm_event)
    monkeypatch.setattr(moderator, "download_media", fake_download_media)
    monkeypatch.setattr(moderator, "run_classifier", fake_run_classifier)
    try:

        async def scenario() -> tuple[
            moderator.ModerationOutcome, dict[str, object] | None
        ]:
            from dmguard.db import get_connection
            from dmguard.repo_senders import get_allowed_sender

            async with get_connection(db_path) as connection:
                outcome = await moderator.moderate_job(
                    build_job(),
                    connection,
                    object(),
                    ["classifier-fake"],
                )
                sender_row = await get_allowed_sender(connection, "sender-1")
                return outcome, sender_row

        outcome, sender_row = run(scenario())
    finally:
        monkeypatch.undo()

    assert outcome.outcome == "safe"
    assert outcome.category_code == "NA: None applying"
    assert outcome.rationale == "No violence found"
    assert outcome.block_attempted is False
    assert sender_row is not None
    assert sender_row["sender_id"] == "sender-1"
    assert sender_row["source_event_id"] == "event-1"
    assert not download_path.exists()


def test_moderate_job_marks_unsafe_photo_as_blocked_with_mock_block_call(
    tmp_path: Path,
) -> None:
    import dmguard.moderator as moderator

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    download_path = tmp_path / "downloaded-photo.jpg"

    photo = MediaItem(
        media_key="3_1",
        type="photo",
        url="https://example.com/photo.jpg",
    )

    async def fake_fetch_dm_event(*_args, **_kwargs) -> DMEvent:
        return build_event(photo)

    async def fake_download_media(*_args, **_kwargs) -> Path:
        download_path.write_bytes(b"photo-bytes")
        return download_path

    def fake_run_classifier(*_args, **_kwargs) -> ClassifierResponse:
        return build_response(
            rating="unsafe",
            category="O2: Violence, Harm, or Cruelty",
            rationale="Violence detected",
        )

    async def fake_attempt_block_sender(*_args, **_kwargs) -> bool:
        return True

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(moderator, "fetch_dm_event", fake_fetch_dm_event)
    monkeypatch.setattr(moderator, "download_media", fake_download_media)
    monkeypatch.setattr(moderator, "run_classifier", fake_run_classifier)
    monkeypatch.setattr(moderator, "_attempt_block_sender", fake_attempt_block_sender)
    try:

        async def scenario() -> moderator.ModerationOutcome:
            from dmguard.db import get_connection

            async with get_connection(db_path) as connection:
                return await moderator.moderate_job(
                    build_job(),
                    connection,
                    object(),
                    ["classifier-fake"],
                )

        outcome = run(scenario())
    finally:
        monkeypatch.undo()

    assert outcome.outcome == "blocked"
    assert outcome.category_code == "O2: Violence, Harm, or Cruelty"
    assert outcome.rationale == "Violence detected"
    assert outcome.trigger_frame_index is None
    assert outcome.trigger_time_sec is None
    assert outcome.block_attempted is True
    assert not download_path.exists()


def test_moderate_job_marks_unsafe_video_frame_as_blocked_with_trigger_info(
    tmp_path: Path,
) -> None:
    import dmguard.moderator as moderator

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    video_path = tmp_path / "clip.mp4"
    frame_one_path = tmp_path / "frame-1.jpg"
    frame_two_path = tmp_path / "frame-2.jpg"

    video = MediaItem(
        media_key="3_2",
        type="video",
        preview_image_url="https://example.com/video.jpg",
    )

    async def fake_fetch_dm_event(*_args, **_kwargs) -> DMEvent:
        return build_event(video)

    async def fake_download_media(*_args, **_kwargs) -> Path:
        video_path.write_bytes(b"video-bytes")
        return video_path

    def fake_extract_frames(*_args, **_kwargs) -> list[FrameInfo]:
        frame_one_path.write_bytes(b"frame-1")
        frame_two_path.write_bytes(b"frame-2")
        return [
            FrameInfo(path=frame_one_path, time_sec=1.0, index=0),
            FrameInfo(path=frame_two_path, time_sec=2.0, index=1),
        ]

    responses = iter(
        [
            build_response(
                rating="safe",
                category="NA: None applying",
                rationale="first frame safe",
            ),
            build_response(
                rating="unsafe",
                category="O2: Violence, Harm, or Cruelty",
                rationale="second frame unsafe",
            ),
        ]
    )

    def fake_run_classifier(*_args, **_kwargs) -> ClassifierResponse:
        return next(responses)

    async def fake_attempt_block_sender(*_args, **_kwargs) -> bool:
        return True

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(moderator, "fetch_dm_event", fake_fetch_dm_event)
    monkeypatch.setattr(moderator, "download_media", fake_download_media)
    monkeypatch.setattr(moderator, "extract_frames", fake_extract_frames)
    monkeypatch.setattr(moderator, "run_classifier", fake_run_classifier)
    monkeypatch.setattr(moderator, "_attempt_block_sender", fake_attempt_block_sender)
    try:

        async def scenario() -> moderator.ModerationOutcome:
            from dmguard.db import get_connection

            async with get_connection(db_path) as connection:
                return await moderator.moderate_job(
                    build_job(),
                    connection,
                    object(),
                    ["classifier-fake"],
                )

        outcome = run(scenario())
    finally:
        monkeypatch.undo()

    assert outcome.outcome == "blocked"
    assert outcome.category_code == "O2: Violence, Harm, or Cruelty"
    assert outcome.rationale == "second frame unsafe"
    assert outcome.trigger_frame_index == 1
    assert outcome.trigger_time_sec == 2.0
    assert outcome.block_attempted is True
    assert not video_path.exists()
    assert not frame_one_path.exists()
    assert not frame_two_path.exists()


def test_moderate_job_propagates_classifier_failure_and_cleans_up_temp_files(
    tmp_path: Path,
) -> None:
    import dmguard.moderator as moderator

    db_path = tmp_path / "state.db"
    run(bootstrap_database(db_path))
    download_path = tmp_path / "downloaded-photo.jpg"

    photo = MediaItem(
        media_key="3_1",
        type="photo",
        url="https://example.com/photo.jpg",
    )

    async def fake_fetch_dm_event(*_args, **_kwargs) -> DMEvent:
        return build_event(photo)

    async def fake_download_media(*_args, **_kwargs) -> Path:
        download_path.write_bytes(b"photo-bytes")
        return download_path

    def fake_run_classifier(*_args, **_kwargs) -> ClassifierResponse:
        raise RuntimeError("classifier exploded")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(moderator, "fetch_dm_event", fake_fetch_dm_event)
    monkeypatch.setattr(moderator, "download_media", fake_download_media)
    monkeypatch.setattr(moderator, "run_classifier", fake_run_classifier)
    try:

        async def scenario() -> None:
            from dmguard.db import get_connection

            async with get_connection(db_path) as connection:
                await moderator.moderate_job(
                    build_job(),
                    connection,
                    object(),
                    ["classifier-fake"],
                )

        with pytest.raises(RuntimeError, match="classifier exploded"):
            run(scenario())
    finally:
        monkeypatch.undo()

    assert not download_path.exists()
