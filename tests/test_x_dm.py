import asyncio

import httpx
import pytest


class StubSecretStore:
    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    def get(self, key: str) -> str:
        if key != "x_access_token":
            raise AssertionError(f"Unexpected secret key: {key}")

        return self._access_token


def run(coroutine):
    return asyncio.run(coroutine)


async def fetch_event(
    transport: httpx.MockTransport,
    event_id: str = "1234567890",
):
    from dmguard.x_client import XClient
    from dmguard.x_dm import fetch_dm_event

    async with XClient(StubSecretStore("access-token"), transport=transport) as client:
        return await fetch_dm_event(client, event_id)


def test_fetch_dm_event_uses_expected_endpoint_and_query_params() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/dm_events/1234567890"
        assert request.url.params["event_fields"] == (
            "attachments,created_at,dm_conversation_id,sender_id,text"
        )
        assert request.url.params["expansions"] == "attachments.media_keys,sender_id"
        assert (
            request.url.params["media.fields"] == "type,url,preview_image_url,variants"
        )
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "1234567890",
                    "sender_id": "111",
                    "text": "hello",
                    "created_at": "2026-03-11T00:00:00.000Z",
                }
            },
        )

    dm_event = run(fetch_event(httpx.MockTransport(handler)))

    assert dm_event.event_id == "1234567890"


def test_fetch_dm_event_parses_media_items_from_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "event-1",
                    "sender_id": "sender-1",
                    "text": "hello world",
                    "created_at": "2026-03-11T00:00:00.000Z",
                    "attachments": {"media_keys": ["3_1", "3_2"]},
                },
                "includes": {
                    "media": [
                        {
                            "media_key": "3_1",
                            "type": "photo",
                            "url": "https://example.com/photo.jpg",
                        },
                        {
                            "media_key": "3_2",
                            "type": "video",
                            "preview_image_url": "https://example.com/video.jpg",
                            "variants": [
                                {
                                    "bit_rate": 832000,
                                    "content_type": "video/mp4",
                                    "url": "https://example.com/video.mp4",
                                }
                            ],
                        },
                    ]
                },
            },
        )

    dm_event = run(fetch_event(httpx.MockTransport(handler), event_id="event-1"))

    assert dm_event.model_dump() == {
        "event_id": "event-1",
        "sender_id": "sender-1",
        "text": "hello world",
        "created_at": "2026-03-11T00:00:00.000Z",
        "media_items": [
            {
                "media_key": "3_1",
                "type": "photo",
                "url": "https://example.com/photo.jpg",
                "preview_image_url": None,
                "variants": None,
            },
            {
                "media_key": "3_2",
                "type": "video",
                "url": None,
                "preview_image_url": "https://example.com/video.jpg",
                "variants": [
                    {
                        "bit_rate": 832000,
                        "content_type": "video/mp4",
                        "url": "https://example.com/video.mp4",
                    }
                ],
            },
        ],
    }


def test_fetch_dm_event_returns_empty_media_items_when_attachments_missing() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "event-1",
                    "sender_id": "sender-1",
                    "text": "hello world",
                    "created_at": "2026-03-11T00:00:00.000Z",
                }
            },
        )

    dm_event = run(fetch_event(httpx.MockTransport(handler), event_id="event-1"))

    assert dm_event.media_items == []


def test_fetch_dm_event_returns_empty_media_items_when_media_keys_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "event-1",
                    "sender_id": "sender-1",
                    "text": "hello world",
                    "created_at": "2026-03-11T00:00:00.000Z",
                    "attachments": {"media_keys": []},
                },
                "includes": {"media": []},
            },
        )

    dm_event = run(fetch_event(httpx.MockTransport(handler), event_id="event-1"))

    assert dm_event.media_items == []


def test_fetch_dm_event_propagates_x_api_error() -> None:
    from dmguard.x_client import XApiError

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text='{"error":"bad"}')

    with pytest.raises(XApiError) as exc_info:
        run(fetch_event(httpx.MockTransport(handler), event_id="event-1"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.body == '{"error":"bad"}'
