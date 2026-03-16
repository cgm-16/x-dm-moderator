from unittest.mock import patch

import httpx
import pytest

from tests.conftest import StubSecretStore, run


async def perform_get(transport: httpx.MockTransport) -> str:
    from dmguard.x_client import XClient

    async with XClient(
        StubSecretStore(x_access_token="access-token"), transport=transport
    ) as client:
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

    client = XClient(StubSecretStore(x_access_token="access-token"))

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
            StubSecretStore(x_access_token="access-token"),
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
            StubSecretStore(x_access_token="access-token"),
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.get("/2/test")

    with pytest.raises(XApiError) as exc_info:
        run(perform_request())

    assert exc_info.value.status_code == 500
    assert exc_info.value.body == '{"error":"bad"}'


def test_refreshes_token_on_401_and_retries() -> None:
    from dmguard.x_client import XClient

    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(401, text="Unauthorized")
        return httpx.Response(200, text="ok")

    store = StubSecretStore(
        x_access_token="old-token",
        x_client_id="cid",
        x_refresh_token="old-rt",
    )

    async def mock_refresh(client_id, refresh_token):
        return {"access_token": "new-token", "refresh_token": "new-rt"}

    async def perform_request() -> str:
        async with XClient(store, transport=httpx.MockTransport(handler)) as client:
            with patch("dmguard.x_client.async_refresh_access_token", mock_refresh):
                response = await client.get("/2/test")
                return response.text

    result = run(perform_request())

    assert result == "ok"
    assert store.get("x_access_token") == "new-token"
    assert store.get("x_refresh_token") == "new-rt"


def test_raises_error_when_retry_after_refresh_fails() -> None:
    from dmguard.x_client import XApiError, XClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    store = StubSecretStore(
        x_access_token="token",
        x_client_id="cid",
        x_refresh_token="rt",
    )

    async def mock_refresh(client_id, refresh_token):
        return {"access_token": "new-token", "refresh_token": "new-rt"}

    async def perform_request() -> None:
        async with XClient(store, transport=httpx.MockTransport(handler)) as client:
            with patch("dmguard.x_client.async_refresh_access_token", mock_refresh):
                await client.get("/2/test")

    with pytest.raises(XApiError) as exc_info:
        run(perform_request())

    assert exc_info.value.status_code == 401


def test_raises_error_when_refresh_itself_fails() -> None:
    from dmguard.x_client import XApiError, XClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    store = StubSecretStore(
        x_access_token="token",
        x_client_id="cid",
        x_refresh_token="rt",
    )

    async def mock_refresh(client_id, refresh_token):
        raise RuntimeError("refresh exploded")

    async def perform_request() -> None:
        async with XClient(store, transport=httpx.MockTransport(handler)) as client:
            with patch("dmguard.x_client.async_refresh_access_token", mock_refresh):
                await client.get("/2/test")

    with pytest.raises(XApiError) as exc_info:
        run(perform_request())

    assert exc_info.value.status_code == 401
    assert "Token refresh failed" in exc_info.value.body
