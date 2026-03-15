from pathlib import Path

import pytest


def write_secrets_file(tmp_path: Path, content: str) -> Path:
    secrets_path = tmp_path / "secrets.bin"
    secrets_path.write_text(content, encoding="utf-8")
    return secrets_path


def test_file_secret_store_get_returns_expected_value(tmp_path: Path) -> None:
    from dmguard.secrets import FileSecretStore

    secrets_path = write_secrets_file(
        tmp_path,
        """
{
  "duckdns_token": "duckdns-token",
  "x_access_token": "access-token",
  "x_consumer_secret": "consumer-secret",
  "hf_token": "hf-token"
}
""".strip(),
    )

    store = FileSecretStore(secrets_path)

    assert store.get("duckdns_token") == "duckdns-token"
    assert store.get("x_access_token") == "access-token"
    assert store.get("hf_token") == "hf-token"


def test_file_secret_store_raises_missing_secret_error_for_unknown_key(
    tmp_path: Path,
) -> None:
    from dmguard.secrets import FileSecretStore, MissingSecretError

    secrets_path = write_secrets_file(
        tmp_path,
        """
{
  "duckdns_token": "duckdns-token",
  "x_access_token": "access-token",
  "x_consumer_secret": "consumer-secret",
  "hf_token": "hf-token"
}
""".strip(),
    )

    store = FileSecretStore(secrets_path)

    with pytest.raises(MissingSecretError) as exc_info:
        store.get("not-a-real-key")

    assert "not-a-real-key" in str(exc_info.value)


def test_file_secret_store_raises_file_not_found_for_missing_file(
    tmp_path: Path,
) -> None:
    from dmguard.secrets import FileSecretStore

    missing_path = tmp_path / "missing-secrets.bin"
    store = FileSecretStore(missing_path)

    with pytest.raises(FileNotFoundError) as exc_info:
        store.get("x_access_token")

    assert str(missing_path) in str(exc_info.value)


def test_file_secret_store_uses_default_secrets_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import secrets

    secrets_path = write_secrets_file(
        tmp_path,
        """
{
  "duckdns_token": "duckdns-token",
  "x_access_token": "access-token",
  "x_consumer_secret": "consumer-secret",
  "hf_token": "hf-token"
}
""".strip(),
    )

    monkeypatch.setattr(secrets, "SECRETS_PATH", secrets_path)

    store = secrets.FileSecretStore()

    assert store.get("x_consumer_secret") == "consumer-secret"


def test_file_secret_store_update_persists_value(tmp_path: Path) -> None:
    from dmguard.secrets import FileSecretStore

    secrets_path = write_secrets_file(
        tmp_path,
        '{"duckdns_token": "old", "x_access_token": "old-token",'
        ' "x_consumer_secret": "cs", "hf_token": "hf"}',
    )

    store = FileSecretStore(secrets_path)
    store.update("x_access_token", "new-token")

    assert store.get("x_access_token") == "new-token"
    assert store.get("duckdns_token") == "old"


def test_file_secret_store_update_rejects_unknown_key(tmp_path: Path) -> None:
    from dmguard.secrets import FileSecretStore, MissingSecretError

    secrets_path = write_secrets_file(
        tmp_path,
        '{"duckdns_token": "t", "x_access_token": "a",'
        ' "x_consumer_secret": "cs", "hf_token": "hf"}',
    )

    store = FileSecretStore(secrets_path)

    with pytest.raises(MissingSecretError):
        store.update("bogus_key", "value")
