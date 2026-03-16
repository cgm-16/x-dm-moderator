import asyncio
import base64
import hashlib
import threading
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


def test_generate_pkce_pair_length_and_s256() -> None:
    from dmguard.x_oauth import generate_pkce_pair

    verifier, challenge = generate_pkce_pair()

    assert len(verifier) == 43
    expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected_challenge = (
        base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
    )
    assert challenge == expected_challenge


def test_build_authorization_url_params() -> None:
    from dmguard.x_oauth import (
        AUTHORIZATION_URL,
        REDIRECT_URI,
        SCOPES,
        build_authorization_url,
    )

    url = build_authorization_url("my-client-id", "my-challenge", "my-state")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert url.startswith(AUTHORIZATION_URL)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["my-client-id"]
    assert params["redirect_uri"] == [REDIRECT_URI]
    assert params["scope"] == [SCOPES]
    assert params["state"] == ["my-state"]
    assert params["code_challenge"] == ["my-challenge"]
    assert params["code_challenge_method"] == ["S256"]


def test_exchange_code_sends_correct_payload() -> None:
    from dmguard.x_oauth import exchange_code_for_tokens

    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["body"] = request.content.decode("utf-8")
        captured_request["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"access_token": "at-123", "refresh_token": "rt-456"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = exchange_code_for_tokens(
        "cid", "auth-code", "verifier-abc", http_client=client
    )

    assert result == {"access_token": "at-123", "refresh_token": "rt-456"}
    assert "grant_type=authorization_code" in captured_request["body"]
    assert "code=auth-code" in captured_request["body"]
    assert "client_id=cid" in captured_request["body"]
    assert "code_verifier=verifier-abc" in captured_request["body"]


def test_exchange_code_raises_on_error() -> None:
    from dmguard.x_oauth import OAuthCallbackError, exchange_code_for_tokens

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(OAuthCallbackError, match="Token exchange failed"):
        exchange_code_for_tokens("cid", "bad-code", "verifier", http_client=client)


def test_refresh_sends_correct_payload() -> None:
    from dmguard.x_oauth import refresh_access_token

    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={"access_token": "new-at", "refresh_token": "new-rt"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = refresh_access_token("cid", "old-rt", http_client=client)

    assert result == {"access_token": "new-at", "refresh_token": "new-rt"}
    assert "grant_type=refresh_token" in captured_request["body"]
    assert "refresh_token=old-rt" in captured_request["body"]
    assert "client_id=cid" in captured_request["body"]


def test_async_refresh_sends_correct_payload() -> None:
    from dmguard.x_oauth import async_refresh_access_token

    captured_request = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_request["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={"access_token": "new-at", "refresh_token": "new-rt"},
        )

    async def run_refresh() -> dict[str, str]:
        transport = httpx.MockTransport(handler)
        # Patch AsyncClient to use mock transport
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, **kwargs):
            kwargs["transport"] = transport
            original_init(self, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx.AsyncClient, "__init__", patched_init)
            return await async_refresh_access_token("cid", "old-rt")

    result = asyncio.run(run_refresh())

    assert result == {"access_token": "new-at", "refresh_token": "new-rt"}
    assert "grant_type=refresh_token" in captured_request["body"]
    assert "refresh_token=old-rt" in captured_request["body"]
    assert "client_id=cid" in captured_request["body"]


def test_fetch_user_id_returns_id() -> None:
    from dmguard.x_oauth import fetch_authenticated_user_id

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer my-token"
        return httpx.Response(200, json={"data": {"id": "12345"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    user_id = fetch_authenticated_user_id("my-token", http_client=client)

    assert user_id == "12345"


def test_callback_handler_captures_code() -> None:
    import http.server
    from urllib.parse import urlencode

    from dmguard.x_oauth import _make_callback_handler

    callback_result: dict[str, str] = {}
    handler_class = _make_callback_handler(callback_result)
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_class)
    port = server.server_address[1]
    server.timeout = 5

    thread = threading.Thread(target=server.handle_request)
    thread.start()

    params = urlencode({"code": "test-code", "state": "test-state"})
    response = httpx.get(f"http://127.0.0.1:{port}/callback?{params}")

    thread.join(timeout=5)
    server.server_close()

    assert response.status_code == 200
    assert callback_result["code"] == "test-code"
    assert callback_result["state"] == "test-state"


def test_callback_handler_captures_error() -> None:
    import http.server
    from urllib.parse import urlencode

    from dmguard.x_oauth import _make_callback_handler

    callback_result: dict[str, str] = {}
    handler_class = _make_callback_handler(callback_result)
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_class)
    port = server.server_address[1]
    server.timeout = 5

    thread = threading.Thread(target=server.handle_request)
    thread.start()

    params = urlencode({"error": "access_denied"})
    response = httpx.get(f"http://127.0.0.1:{port}/callback?{params}")

    thread.join(timeout=5)
    server.server_close()

    assert response.status_code == 200
    assert callback_result["error"] == "access_denied"
