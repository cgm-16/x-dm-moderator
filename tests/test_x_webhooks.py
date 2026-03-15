import httpx
import pytest

from tests.conftest import StubSecretStore, run


async def ensure_webhook(
    transport: httpx.MockTransport,
    *,
    webhook_url: str = "https://dmguard.duckdns.org/webhooks/x",
) -> dict[str, object]:
    from dmguard.x_client import XClient
    from dmguard.x_webhooks import ensure_webhook_registered

    async with XClient(
        StubSecretStore(x_access_token="access-token"),
        transport=transport,
    ) as client:
        return await ensure_webhook_registered(client, webhook_url)


def test_ensure_webhook_registered_returns_matching_valid_webhook() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "wh-1",
                        "url": "https://dmguard.duckdns.org/webhooks/x",
                        "valid": True,
                        "created_at": "2026-03-15T00:00:00Z",
                    }
                ]
            },
        )

    webhook = run(ensure_webhook(httpx.MockTransport(handler)))

    assert webhook == {
        "id": "wh-1",
        "url": "https://dmguard.duckdns.org/webhooks/x",
        "valid": True,
        "created_at": "2026-03-15T00:00:00Z",
    }
    assert requests == [("GET", "/2/webhooks")]


def test_ensure_webhook_registered_creates_webhook_when_missing() -> None:
    requests: list[tuple[str, str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = request.content.decode("utf-8") if request.content else None
        requests.append((request.method, request.url.path, payload))
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})

        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "wh-new",
                    "url": "https://dmguard.duckdns.org/webhooks/x",
                    "valid": True,
                    "created_at": "2026-03-15T00:00:00Z",
                }
            },
        )

    webhook = run(ensure_webhook(httpx.MockTransport(handler)))

    assert webhook["id"] == "wh-new"
    assert webhook["valid"] is True
    assert [item[:2] for item in requests] == [
        ("GET", "/2/webhooks"),
        ("POST", "/2/webhooks"),
    ]
    assert requests[1][2] == '{"url":"https://dmguard.duckdns.org/webhooks/x"}'


def test_ensure_webhook_registered_revalidates_invalid_matching_webhook() -> None:
    requests: list[tuple[str, str]] = []
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "wh-1",
                            "url": "https://dmguard.duckdns.org/webhooks/x",
                            "valid": False,
                            "created_at": "2026-03-15T00:00:00Z",
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"data": {"attempted": True}}),
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "wh-1",
                            "url": "https://dmguard.duckdns.org/webhooks/x",
                            "valid": True,
                            "created_at": "2026-03-15T00:00:00Z",
                        }
                    ]
                },
            ),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return next(responses)

    webhook = run(ensure_webhook(httpx.MockTransport(handler)))

    assert webhook["id"] == "wh-1"
    assert webhook["valid"] is True
    assert requests == [
        ("GET", "/2/webhooks"),
        ("PUT", "/2/webhooks/wh-1"),
        ("GET", "/2/webhooks"),
    ]


def test_ensure_webhook_registered_raises_when_validation_does_not_produce_valid_webhook() -> (
    None
):
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "wh-1",
                            "url": "https://dmguard.duckdns.org/webhooks/x",
                            "valid": False,
                            "created_at": "2026-03-15T00:00:00Z",
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"data": {"attempted": True}}),
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "wh-1",
                            "url": "https://dmguard.duckdns.org/webhooks/x",
                            "valid": False,
                            "created_at": "2026-03-15T00:00:00Z",
                        }
                    ]
                },
            ),
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    with pytest.raises(ValueError, match="valid"):
        run(ensure_webhook(httpx.MockTransport(handler)))
