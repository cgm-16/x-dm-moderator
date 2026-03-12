from pathlib import Path
from urllib.parse import urlparse
import logging

import httpx

from dmguard.paths import TMP_DIR
from dmguard.x_client import RateLimitedError, XApiError, XClient
from dmguard.x_dm import MediaItem


_DEFAULT_EXTENSIONS = {
    "animated_gif": ".mp4",
    "photo": ".jpg",
    "video": ".mp4",
}

_LOGGER = logging.getLogger("dmguard")
_SIZE_CAPPED_MEDIA_TYPES = {"animated_gif", "video"}
MAX_CAPPED_MEDIA_DOWNLOAD_BYTES = 25 * 1024 * 1024


class MediaTooLargeError(Exception):
    pass


async def download_media(client: XClient, item: MediaItem, event_id: str) -> Path:
    download_type, download_url = await _resolve_download_target(client, item)
    destination_path = TMP_DIR / (
        f"{event_id}_{item.media_key}{_resolve_extension(download_type, download_url)}"
    )

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    response = await client.get(download_url)
    destination_path.write_bytes(response.content)

    return destination_path


def cleanup_media(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            _LOGGER.warning("temporary media file already missing: %s", path)


async def _resolve_download_target(client: XClient, item: MediaItem) -> tuple[str, str]:
    download_url = _resolve_download_url(item)

    if item.type not in _SIZE_CAPPED_MEDIA_TYPES:
        return item.type, download_url

    content_length = await _probe_content_length(client, download_url)

    if content_length is None or content_length <= MAX_CAPPED_MEDIA_DOWNLOAD_BYTES:
        return item.type, download_url

    if item.preview_image_url:
        return "photo", item.preview_image_url

    raise MediaTooLargeError(
        f"Media item {item.media_key} exceeds {MAX_CAPPED_MEDIA_DOWNLOAD_BYTES} bytes"
    )


def _resolve_download_url(item: MediaItem) -> str:
    if item.type == "photo" and item.url:
        return item.url

    variant_url = _select_variant_url(item.variants)

    if variant_url:
        return variant_url

    raise ValueError(f"Media item {item.media_key} does not have a downloadable URL")


def _select_variant_url(variants: list[dict[str, object]] | None) -> str | None:
    if not variants:
        return None

    first_usable_url: str | None = None
    best_url: str | None = None
    best_bitrate: int | None = None

    for variant in variants:
        url = variant.get("url")

        if not isinstance(url, str):
            continue

        if first_usable_url is None:
            first_usable_url = url

        bitrate = _parse_bitrate(variant.get("bit_rate"))

        if bitrate is None:
            continue

        if best_bitrate is None or bitrate > best_bitrate:
            best_bitrate = bitrate
            best_url = url

    return best_url or first_usable_url


def _parse_bitrate(raw_bitrate: object) -> int | None:
    if isinstance(raw_bitrate, bool):
        return None

    if isinstance(raw_bitrate, int):
        return raw_bitrate

    if isinstance(raw_bitrate, float):
        return int(raw_bitrate)

    return None


async def _probe_content_length(client: XClient, download_url: str) -> int | None:
    try:
        response = await client.request("HEAD", download_url)
    except (httpx.HTTPError, RateLimitedError, XApiError):
        return None

    return _parse_content_length(response.headers.get("Content-Length"))


def _parse_content_length(raw_content_length: str | None) -> int | None:
    if raw_content_length is None:
        return None

    try:
        content_length = int(raw_content_length)
    except ValueError:
        return None

    if content_length < 0:
        return None

    return content_length


def _resolve_extension(item_type: str, download_url: str) -> str:
    parsed_path = Path(urlparse(download_url).path)

    if parsed_path.suffix:
        return parsed_path.suffix

    return _DEFAULT_EXTENSIONS.get(item_type, "")


__all__ = ["MediaTooLargeError", "cleanup_media", "download_media"]
