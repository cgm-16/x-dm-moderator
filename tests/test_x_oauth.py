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


def test_fetch_user_id_returns_id() -> None:
    from dmguard.x_oauth import fetch_authenticated_user_id

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer my-token"
        return httpx.Response(200, json={"data": {"id": "12345"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    user_id = fetch_authenticated_user_id("my-token", http_client=client)

    assert user_id == "12345"


def test_callback_server_captures_code() -> None:
    import http.server
    from urllib.parse import urlencode

    from dmguard.x_oauth import CALLBACK_PORT

    callback_result: dict[str, str] = {}

    class TestHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            callback_result["code"] = query.get("code", [""])[0]
            callback_result["state"] = query.get("state", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), TestHandler)
    server.timeout = 5

    thread = threading.Thread(target=server.handle_request)
    thread.start()

    params = urlencode({"code": "test-code", "state": "test-state"})
    response = httpx.get(f"http://127.0.0.1:{CALLBACK_PORT}/callback?{params}")

    thread.join(timeout=5)
    server.server_close()

    assert response.status_code == 200
    assert callback_result["code"] == "test-code"
    assert callback_result["state"] == "test-state"
