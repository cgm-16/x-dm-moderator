from pathlib import Path
import logging

import httpx
import pytest

from dmguard.x_dm import MediaItem
from tests.conftest import StubSecretStore, clear_logger, run


@pytest.fixture(autouse=True)
def reset_dmguard_logger() -> None:
    clear_logger("dmguard")

    yield

    clear_logger("dmguard")


async def download_item(
    item: MediaItem,
    *,
    event_id: str = "event-1",
    transport: httpx.MockTransport,
) -> Path:
    from dmguard.media_download import download_media
    from dmguard.x_client import XClient

    async with XClient(
        StubSecretStore(x_access_token="access-token"),
        transport=transport,
    ) as client:
        return await download_media(client, item, event_id)


def test_download_media_downloads_photo_to_tmp_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.media_download as media_download

    download_dir = tmp_path / "downloads"
    photo = MediaItem(
        media_key="3_1",
        type="photo",
        url="https://media.example.com/path/photo.jpg",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://media.example.com/path/photo.jpg")
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(200, content=b"photo-bytes")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    downloaded_path = run(download_item(photo, transport=httpx.MockTransport(handler)))

    assert downloaded_path == download_dir / "event-1_3_1.jpg"
    assert downloaded_path.read_bytes() == b"photo-bytes"


def test_download_media_uses_highest_bitrate_variant_for_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.media_download as media_download

    download_dir = tmp_path / "downloads"
    video = MediaItem(
        media_key="3_2",
        type="video",
        variants=[
            {
                "bit_rate": 256000,
                "content_type": "video/mp4",
                "url": "https://media.example.com/video-low.mp4",
            },
            {
                "bit_rate": 832000,
                "content_type": "video/mp4",
                "url": "https://media.example.com/video-high.mp4?tag=1",
            },
        ],
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://media.example.com/video-high.mp4?tag=1"
        )
        return httpx.Response(200, content=b"video-bytes")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    downloaded_path = run(download_item(video, transport=httpx.MockTransport(handler)))

    assert downloaded_path == download_dir / "event-1_3_2.mp4"
    assert downloaded_path.read_bytes() == b"video-bytes"


def test_download_media_uses_first_variant_when_bitrate_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.media_download as media_download

    download_dir = tmp_path / "downloads"
    animated_gif = MediaItem(
        media_key="3_3",
        type="animated_gif",
        variants=[
            {
                "content_type": "video/mp4",
                "url": "https://media.example.com/gif-first.mp4",
            },
            {
                "content_type": "video/mp4",
                "url": "https://media.example.com/gif-second.mp4",
            },
        ],
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://media.example.com/gif-first.mp4")
        return httpx.Response(200, content=b"gif-bytes")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    downloaded_path = run(
        download_item(animated_gif, transport=httpx.MockTransport(handler))
    )

    assert downloaded_path == download_dir / "event-1_3_3.mp4"
    assert downloaded_path.read_bytes() == b"gif-bytes"


def test_cleanup_media_deletes_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.media_download as media_download

    download_dir = tmp_path / "downloads"
    first_path = download_dir / "event-1_3_1.jpg"
    second_path = download_dir / "event-1_3_2.mp4"
    download_dir.mkdir()
    first_path.write_bytes(b"one")
    second_path.write_bytes(b"two")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    media_download.cleanup_media([first_path, second_path])

    assert not first_path.exists()
    assert not second_path.exists()


def test_cleanup_media_warns_for_missing_files_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import dmguard.media_download as media_download

    download_dir = tmp_path / "downloads"
    missing_path = download_dir / "event-1_3_9.jpg"

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    with caplog.at_level(logging.WARNING, logger="dmguard"):
        media_download.cleanup_media([missing_path])

    assert caplog.messages == [f"temporary media file already missing: {missing_path}"]
