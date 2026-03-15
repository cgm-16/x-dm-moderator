from abc import ABC, abstractmethod
from pathlib import Path
import json

from dmguard.paths import SECRETS_PATH


SECRET_KEYS = frozenset(
    {
        "duckdns_token",
        "x_access_token",
        "x_refresh_token",
        "x_consumer_secret",
        "x_app_bearer",
        "x_user_id",
        "hf_token",
    }
)


class MissingSecretError(KeyError):
    """Raised when a requested secret is not available."""


class SecretStore(ABC):
    @abstractmethod
    def get(self, key: str) -> str:
        raise NotImplementedError


class FileSecretStore(SecretStore):
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or SECRETS_PATH

    def get(self, key: str) -> str:
        if key not in SECRET_KEYS:
            raise MissingSecretError(f"Unknown secret key: {key}")

        secrets = self._load_secrets()

        try:
            value = secrets[key]
        except KeyError as exc:
            raise MissingSecretError(f"Missing secret value for key: {key}") from exc

        if not isinstance(value, str):
            raise MissingSecretError(f"Secret value for key must be a string: {key}")

        return value

    def _load_secrets(self) -> dict[str, object]:
        with self._path.open(encoding="utf-8") as secrets_file:
            return json.load(secrets_file)


__all__ = ["FileSecretStore", "MissingSecretError", "SECRET_KEYS", "SecretStore"]
