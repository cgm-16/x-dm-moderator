import asyncio

from dmguard.secrets import SecretStore


class StubSecretStore(SecretStore):
    """In-memory secret store for tests. Accepts arbitrary key-value pairs."""

    def __init__(self, **secrets: str) -> None:
        self._secrets = secrets

    def get(self, key: str) -> str:
        try:
            return self._secrets[key]
        except KeyError:
            raise AssertionError(f"Unexpected secret key: {key}") from None


def run(coroutine):
    return asyncio.run(coroutine)
