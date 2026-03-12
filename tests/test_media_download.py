from pathlib import Path
import logging

import httpx
import pytest

from dmguard.x_dm import MediaItem
from tests.conftest import StubSecretStore, clear_logger, run


_TWENTY_FIVE_MB = 25 * 1024 * 1024


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


def test_download_media_uses_highest_bitrate_variant_for_video_under_size_cap(
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
    requests: list[tuple[str, httpx.URL]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url))

        if request.method == "HEAD":
            assert request.url == httpx.URL(
                "https://media.example.com/video-high.mp4?tag=1"
            )
            return httpx.Response(200, headers={"Content-Length": str(_TWENTY_FIVE_MB)})

        assert request.method == "GET"
        assert request.url == httpx.URL(
            "https://media.example.com/video-high.mp4?tag=1"
        )
        return httpx.Response(200, content=b"video-bytes")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    downloaded_path = run(download_item(video, transport=httpx.MockTransport(handler)))

    assert downloaded_path == download_dir / "event-1_3_2.mp4"
    assert downloaded_path.read_bytes() == b"video-bytes"
    assert requests == [
        ("HEAD", httpx.URL("https://media.example.com/video-high.mp4?tag=1")),
        ("GET", httpx.URL("https://media.example.com/video-high.mp4?tag=1")),
    ]


def test_download_media_uses_first_variant_when_bitrate_missing_under_size_cap(
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
    requests: list[tuple[str, httpx.URL]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url))

        if request.method == "HEAD":
            assert request.url == httpx.URL("https://media.example.com/gif-first.mp4")
            return httpx.Response(
                200, headers={"Content-Length": str(_TWENTY_FIVE_MB - 1)}
            )

        assert request.method == "GET"
        assert request.url == httpx.URL("https://media.example.com/gif-first.mp4")
        return httpx.Response(200, content=b"gif-bytes")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    downloaded_path = run(
        download_item(animated_gif, transport=httpx.MockTransport(handler))
    )

    assert downloaded_path == download_dir / "event-1_3_3.mp4"
    assert downloaded_path.read_bytes() == b"gif-bytes"
    assert requests == [
        ("HEAD", httpx.URL("https://media.example.com/gif-first.mp4")),
        ("GET", httpx.URL("https://media.example.com/gif-first.mp4")),
    ]


def test_download_media_uses_preview_image_when_video_exceeds_size_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.media_download as media_download

    download_dir = tmp_path / "downloads"
    video = MediaItem(
        media_key="3_4",
        type="video",
        preview_image_url="https://media.example.com/video-preview.jpg",
        variants=[
            {
                "bit_rate": 832000,
                "content_type": "video/mp4",
                "url": "https://media.example.com/video-large.mp4",
            }
        ],
    )
    requests: list[tuple[str, httpx.URL]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url))

        if request.method == "HEAD":
            assert request.url == httpx.URL("https://media.example.com/video-large.mp4")
            return httpx.Response(
                200, headers={"Content-Length": str(_TWENTY_FIVE_MB + 1)}
            )

        assert request.method == "GET"
        assert request.url == httpx.URL("https://media.example.com/video-preview.jpg")
        return httpx.Response(200, content=b"preview-bytes")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    downloaded_path = run(download_item(video, transport=httpx.MockTransport(handler)))

    assert downloaded_path == download_dir / "event-1_3_4.jpg"
    assert downloaded_path.read_bytes() == b"preview-bytes"
    assert requests == [
        ("HEAD", httpx.URL("https://media.example.com/video-large.mp4")),
        ("GET", httpx.URL("https://media.example.com/video-preview.jpg")),
    ]


def test_download_media_raises_when_video_exceeds_size_cap_without_preview() -> None:
    from dmguard.media_download import MediaTooLargeError

    video = MediaItem(
        media_key="3_5",
        type="video",
        variants=[
            {
                "bit_rate": 832000,
                "content_type": "video/mp4",
                "url": "https://media.example.com/video-large.mp4",
            }
        ],
    )
    requests: list[tuple[str, httpx.URL]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url))
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"Content-Length": str(_TWENTY_FIVE_MB + 1)})

    with pytest.raises(MediaTooLargeError, match="3_5"):
        run(download_item(video, transport=httpx.MockTransport(handler)))

    assert requests == [
        ("HEAD", httpx.URL("https://media.example.com/video-large.mp4"))
    ]


def test_download_media_downloads_video_when_head_has_no_usable_content_length(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.media_download as media_download

    download_dir = tmp_path / "downloads"
    video = MediaItem(
        media_key="3_6",
        type="video",
        preview_image_url="https://media.example.com/video-preview.jpg",
        variants=[
            {
                "bit_rate": 832000,
                "content_type": "video/mp4",
                "url": "https://media.example.com/video-unknown.mp4",
            }
        ],
    )
    requests: list[tuple[str, httpx.URL]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url))

        if request.method == "HEAD":
            assert request.url == httpx.URL(
                "https://media.example.com/video-unknown.mp4"
            )
            return httpx.Response(200, headers={"Content-Length": "not-a-number"})

        assert request.method == "GET"
        assert request.url == httpx.URL("https://media.example.com/video-unknown.mp4")
        return httpx.Response(200, content=b"video-bytes")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    downloaded_path = run(download_item(video, transport=httpx.MockTransport(handler)))

    assert downloaded_path == download_dir / "event-1_3_6.mp4"
    assert downloaded_path.read_bytes() == b"video-bytes"
    assert requests == [
        ("HEAD", httpx.URL("https://media.example.com/video-unknown.mp4")),
        ("GET", httpx.URL("https://media.example.com/video-unknown.mp4")),
    ]


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


def test_download_media_raises_for_item_with_no_downloadable_url() -> None:
    item = MediaItem(
        media_key="3_9",
        type="photo",
        # no url, no variants
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not make an HTTP request")

    with pytest.raises(ValueError, match="3_9"):
        run(download_item(item, transport=httpx.MockTransport(handler)))


def test_download_media_raises_xapierror_on_http_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.media_download as media_download
    from dmguard.x_client import XApiError

    download_dir = tmp_path / "downloads"
    photo = MediaItem(
        media_key="3_1",
        type="photo",
        url="https://media.example.com/path/photo.jpg",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"forbidden")

    monkeypatch.setattr(media_download, "TMP_DIR", download_dir)

    with pytest.raises(XApiError) as exc_info:
        run(download_item(photo, transport=httpx.MockTransport(handler)))

    assert exc_info.value.status_code == 403
