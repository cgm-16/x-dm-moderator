import base64
from contextlib import contextmanager
import hashlib
import http.server
import secrets
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import httpx


AUTHORIZATION_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_ENDPOINT = "https://api.x.com/2/oauth2/token"
REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "dm.read block.write offline.access"
CALLBACK_PORT = 8765
TOKEN_TIMEOUT_SECONDS = 30.0


class OAuthCallbackError(Exception):
    """Raised when the OAuth callback fails or times out."""


@contextmanager
def _owned_client(http_client: httpx.Client | None = None):
    """Yield an httpx.Client, closing it only if we created it."""
    client = http_client or httpx.Client(timeout=TOKEN_TIMEOUT_SECONDS)
    try:
        yield client
    finally:
        if http_client is None:
            client.close()


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256 method."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(client_id: str, code_challenge: str, state: str) -> str:
    """Build the full X OAuth 2.0 authorization URL with PKCE params."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def exchange_code_for_tokens(
    client_id: str,
    code: str,
    code_verifier: str,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, str]:
    """Exchange authorization code for access and refresh tokens."""
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    with _owned_client(http_client) as client:
        response = client.post(TOKEN_ENDPOINT, data=payload)

    if response.is_error:
        raise OAuthCallbackError(
            f"Token exchange failed ({response.status_code}): {response.text}"
        )

    data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
    }


def refresh_access_token(
    client_id: str,
    refresh_token: str,
    *,
    http_client: httpx.Client | None = None,
) -> dict[str, str]:
    """Refresh an expired access token using the refresh token."""
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    with _owned_client(http_client) as client:
        response = client.post(TOKEN_ENDPOINT, data=payload)

    if response.is_error:
        raise OAuthCallbackError(
            f"Token refresh failed ({response.status_code}): {response.text}"
        )

    data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
    }


def fetch_authenticated_user_id(
    access_token: str,
    *,
    http_client: httpx.Client | None = None,
) -> str:
    """Fetch the authenticated user's ID from X API."""
    with _owned_client(http_client) as client:
        response = client.get(
            "https://api.x.com/2/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.is_error:
        raise OAuthCallbackError(
            f"Failed to fetch user ({response.status_code}): {response.text}"
        )

    return response.json()["data"]["id"]


async def async_refresh_access_token(
    client_id: str,
    refresh_token: str,
) -> dict[str, str]:
    """Refresh an expired access token using the refresh token (async)."""
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    async with httpx.AsyncClient(timeout=TOKEN_TIMEOUT_SECONDS) as client:
        response = await client.post(TOKEN_ENDPOINT, data=payload)

    if response.is_error:
        raise OAuthCallbackError(
            f"Token refresh failed ({response.status_code}): {response.text}"
        )

    data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
    }


def _make_callback_handler(
    callback_result: dict[str, str],
) -> type[http.server.BaseHTTPRequestHandler]:
    """Build an HTTP request handler that captures the OAuth callback params."""

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)

            if "error" in query:
                callback_result["error"] = query["error"][0]
            else:
                callback_result["code"] = query.get("code", [""])[0]
                callback_result["state"] = query.get("state", [""])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authorization complete</h1>"
                b"<p>You can close this tab.</p></body></html>"
            )

        def log_message(self, format, *args) -> None:
            pass

    return CallbackHandler


def run_pkce_flow(client_id: str) -> dict[str, str]:
    """Run the full OAuth 2.0 PKCE flow and return tokens + user ID.

    Opens the user's browser for authorization, waits for the callback,
    exchanges the code for tokens, and fetches the authenticated user ID.

    Returns dict with keys: x_access_token, x_refresh_token, x_user_id
    """
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = build_authorization_url(client_id, code_challenge, state)

    callback_result: dict[str, str] = {}

    try:
        server = http.server.HTTPServer(
            ("127.0.0.1", CALLBACK_PORT),
            _make_callback_handler(callback_result),
        )
    except OSError as exc:
        raise OAuthCallbackError(
            f"Cannot start callback server on port {CALLBACK_PORT}: {exc}"
        ) from exc
    server.timeout = 120

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    print(f"Open this URL to authorize:\n{auth_url}")

    server.handle_request()
    server.server_close()

    if "error" in callback_result:
        raise OAuthCallbackError(f"Authorization denied: {callback_result['error']}")

    if not callback_result.get("code"):
        raise OAuthCallbackError("Authorization timed out")

    if callback_result.get("state") != state:
        raise OAuthCallbackError("State mismatch in OAuth callback")

    tokens = exchange_code_for_tokens(client_id, callback_result["code"], code_verifier)
    user_id = fetch_authenticated_user_id(tokens["access_token"])

    return {
        "x_access_token": tokens["access_token"],
        "x_refresh_token": tokens["refresh_token"],
        "x_user_id": user_id,
    }


__all__ = [
    "AUTHORIZATION_URL",
    "CALLBACK_PORT",
    "OAuthCallbackError",
    "REDIRECT_URI",
    "SCOPES",
    "TOKEN_ENDPOINT",
    "TOKEN_TIMEOUT_SECONDS",
    "async_refresh_access_token",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "fetch_authenticated_user_id",
    "generate_pkce_pair",
    "refresh_access_token",
    "run_pkce_flow",
]
