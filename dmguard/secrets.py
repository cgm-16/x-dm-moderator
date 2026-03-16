from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import NamedTemporaryFile
import json
import os

from dmguard.paths import SECRETS_PATH


SECRET_KEYS = frozenset(
    {
        "duckdns_token",
        "x_access_token",
        "x_client_id",
        "x_consumer_secret",
        "x_refresh_token",
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

    @abstractmethod
    def update(self, key: str, value: str) -> None:
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

    def update(self, key: str, value: str) -> None:
        if key not in SECRET_KEYS:
            raise MissingSecretError(f"Unknown secret key: {key}")

        secrets = self._load_secrets()
        secrets[key] = value
        payload = json.dumps(secrets, indent=2)

        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)

        os.replace(temp_path, self._path)

    def _load_secrets(self) -> dict[str, object]:
        with self._path.open(encoding="utf-8") as secrets_file:
            return json.load(secrets_file)


__all__ = ["FileSecretStore", "MissingSecretError", "SECRET_KEYS", "SecretStore"]
