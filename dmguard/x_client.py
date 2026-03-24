import httpx

from dmguard.secrets import SecretStore
from dmguard.x_oauth import async_refresh_access_token

DEFAULT_RETRY_AFTER_SECONDS = 1


class RateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"X API rate limited for {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds


class XApiError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"X API returned {status_code}")
        self.status_code = status_code
        self.body = body


class XClient:
    def __init__(
        self,
        secret_store: SecretStore,
        *,
        base_url: str = "https://api.x.com",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=transport,
        )

    @property
    def authenticated_user_id(self) -> str:
        return self._secret_store.get("x_user_id")

    async def __aenter__(self) -> "XClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        response = await self._request_with_current_token(method, url, **kwargs)

        if response.status_code == 429:
            raise RateLimitedError(_parse_retry_after(response))

        # Single-worker architecture: no guard against concurrent refresh races.
        if response.status_code == 401:
            await self._refresh_token()
            response = await self._request_with_current_token(method, url, **kwargs)
            if response.status_code == 429:
                raise RateLimitedError(_parse_retry_after(response))

        if response.is_error:
            raise XApiError(response.status_code, response.text)

        return response

    async def _refresh_token(self) -> None:
        """Refresh the OAuth access token and update stored secrets."""
        try:
            client_id = self._secret_store.get("x_client_id")
            old_refresh_token = self._secret_store.get("x_refresh_token")
            tokens = await async_refresh_access_token(client_id, old_refresh_token)
            self._secret_store.update("x_access_token", tokens["access_token"])
            self._secret_store.update("x_refresh_token", tokens["refresh_token"])
        except Exception as exc:
            raise XApiError(401, f"Token refresh failed: {exc}") from exc

    async def _request_with_current_token(
        self,
        method: str,
        url: str,
        **kwargs: object,
    ) -> httpx.Response:
        request_kwargs = dict(kwargs)
        headers = httpx.Headers(request_kwargs.get("headers"))
        headers["Authorization"] = f"Bearer {self._secret_store.get('x_access_token')}"
        request_kwargs["headers"] = headers
        return await self._client.request(method, url, **request_kwargs)

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: object) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)


def _parse_retry_after(response: httpx.Response) -> int:
    retry_after = response.headers.get("Retry-After")

    try:
        retry_after_seconds = int(retry_after)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_SECONDS

    return max(retry_after_seconds, DEFAULT_RETRY_AFTER_SECONDS)


__all__ = ["RateLimitedError", "XApiError", "XClient"]
