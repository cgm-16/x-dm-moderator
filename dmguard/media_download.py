from pathlib import Path
from urllib.parse import urlparse
import logging

from dmguard.paths import TMP_DIR
from dmguard.x_client import XClient
from dmguard.x_dm import MediaItem


_DEFAULT_EXTENSIONS = {
    "animated_gif": ".mp4",
    "photo": ".jpg",
    "video": ".mp4",
}

_LOGGER = logging.getLogger("dmguard")


async def download_media(client: XClient, item: MediaItem, event_id: str) -> Path:
    download_url = _resolve_download_url(item)
    destination_path = TMP_DIR / (
        f"{event_id}_{item.media_key}{_resolve_extension(item, download_url)}"
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


def _resolve_extension(item: MediaItem, download_url: str) -> str:
    parsed_path = Path(urlparse(download_url).path)

    if parsed_path.suffix:
        return parsed_path.suffix

    return _DEFAULT_EXTENSIONS.get(item.type, "")


__all__ = ["cleanup_media", "download_media"]
