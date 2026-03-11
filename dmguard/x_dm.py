from pydantic import BaseModel, Field

from dmguard.x_client import XClient


_DM_EVENT_FIELDS = "attachments,created_at,dm_conversation_id,sender_id,text"
_DM_EXPANSIONS = "attachments.media_keys,sender_id"
_DM_MEDIA_FIELDS = "type,url,preview_image_url,variants"


class MediaItem(BaseModel):
    media_key: str
    type: str
    url: str | None = None
    preview_image_url: str | None = None
    variants: list[dict[str, object]] | None = None


class DMEvent(BaseModel):
    event_id: str
    sender_id: str
    text: str
    created_at: str
    media_items: list[MediaItem] = Field(default_factory=list)


async def fetch_dm_event(client: XClient, event_id: str) -> DMEvent:
    response = await client.get(
        f"/2/dm_events/{event_id}",
        params={
            "event_fields": _DM_EVENT_FIELDS,
            "expansions": _DM_EXPANSIONS,
            "media.fields": _DM_MEDIA_FIELDS,
        },
    )
    payload = response.json()
    event = payload["data"]

    return DMEvent.model_validate(
        {
            "event_id": event["id"],
            "sender_id": event["sender_id"],
            "text": event["text"],
            "created_at": event["created_at"],
            "media_items": _build_media_items(payload),
        }
    )


def _build_media_items(payload: dict[str, object]) -> list[dict[str, object]]:
    event = payload["data"]
    attachments = event.get("attachments")

    if not isinstance(attachments, dict):
        return []

    media_keys = attachments.get("media_keys")

    if not isinstance(media_keys, list) or not media_keys:
        return []

    includes = payload.get("includes")

    if not isinstance(includes, dict):
        return []

    included_media = includes.get("media")

    if not isinstance(included_media, list):
        return []

    media_by_key = {
        media_item["media_key"]: media_item
        for media_item in included_media
        if isinstance(media_item, dict) and "media_key" in media_item
    }

    return [
        media_by_key[media_key] for media_key in media_keys if media_key in media_by_key
    ]


__all__ = ["DMEvent", "MediaItem", "fetch_dm_event"]
