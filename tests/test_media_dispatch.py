import logging

import pytest

from dmguard.x_dm import DMEvent, MediaItem
from tests.conftest import clear_logger


@pytest.fixture(autouse=True)
def reset_dmguard_logger() -> None:
    clear_logger("dmguard")

    yield

    clear_logger("dmguard")


def build_event(*media_items: MediaItem) -> DMEvent:
    return DMEvent(
        event_id="event-1",
        sender_id="sender-1",
        text="hello world",
        created_at="2026-03-12T00:00:00.000Z",
        media_items=list(media_items),
    )


def test_dispatch_media_returns_photos_as_is() -> None:
    from dmguard.media_dispatch import dispatch_media

    photo = MediaItem(
        media_key="3_1",
        type="photo",
        url="https://example.com/photo.jpg",
    )

    assert dispatch_media(build_event(photo)) == [photo]


def test_dispatch_media_returns_videos_and_gifs_as_is() -> None:
    from dmguard.media_dispatch import dispatch_media

    video = MediaItem(
        media_key="3_1",
        type="video",
        preview_image_url="https://example.com/video.jpg",
    )
    animated_gif = MediaItem(
        media_key="3_2",
        type="animated_gif",
        preview_image_url="https://example.com/gif.jpg",
    )

    assert dispatch_media(build_event(video, animated_gif)) == [video, animated_gif]


def test_dispatch_media_logs_and_skips_unknown_types(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from dmguard.media_dispatch import dispatch_media

    unknown = MediaItem(
        media_key="3_1",
        type="poll",
    )

    with caplog.at_level(logging.WARNING, logger="dmguard"):
        dispatched = dispatch_media(build_event(unknown))

    assert dispatched == []
    assert caplog.messages == ["unsupported media type skipped: poll"]


def test_dispatch_media_returns_empty_list_for_empty_media_items() -> None:
    from dmguard.media_dispatch import dispatch_media

    assert dispatch_media(build_event()) == []
