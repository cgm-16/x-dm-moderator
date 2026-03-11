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


async def perform_get(transport: httpx.MockTransport) -> str:
    from dmguard.x_client import XClient

    async with XClient(StubSecretStore("access-token"), transport=transport) as client:
        response = await client.get("/2/test")

    return response.text


def test_x_client_sends_authorization_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(200, text="ok")

    response_body = run(perform_get(httpx.MockTransport(handler)))

    assert response_body == "ok"


def test_x_client_uses_ten_second_timeout() -> None:
    from dmguard.x_client import XClient

    client = XClient(StubSecretStore("access-token"))

    try:
        timeout = client._client.timeout

        assert timeout.connect == 10.0
        assert timeout.read == 10.0
        assert timeout.write == 10.0
        assert timeout.pool == 10.0
    finally:
        run(client.aclose())


def test_x_client_raises_rate_limited_error_on_429() -> None:
    from dmguard.x_client import RateLimitedError, XClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "17"})

    async def perform_request() -> None:
        async with XClient(
            StubSecretStore("access-token"),
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.get("/2/test")

    with pytest.raises(RateLimitedError) as exc_info:
        run(perform_request())

    assert exc_info.value.retry_after_seconds == 17


def test_x_client_raises_api_error_on_other_non_success_statuses() -> None:
    from dmguard.x_client import XApiError, XClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text='{"error":"bad"}')

    async def perform_request() -> None:
        async with XClient(
            StubSecretStore("access-token"),
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.get("/2/test")

    with pytest.raises(XApiError) as exc_info:
        run(perform_request())

    assert exc_info.value.status_code == 500
    assert exc_info.value.body == '{"error":"bad"}'
