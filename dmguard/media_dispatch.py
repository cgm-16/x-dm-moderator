import logging

from dmguard.x_dm import DMEvent, MediaItem


_ACTIONABLE_MEDIA_TYPES = {
    "photo",
    "video",
    "animated_gif",
}

_LOGGER = logging.getLogger("dmguard")


def dispatch_media(event: DMEvent) -> list[MediaItem]:
    dispatched: list[MediaItem] = []

    for media_item in event.media_items:
        if media_item.type in _ACTIONABLE_MEDIA_TYPES:
            dispatched.append(media_item)
            continue

        _LOGGER.warning("unsupported media type skipped: %s", media_item.type)

    return dispatched


__all__ = ["dispatch_media"]
