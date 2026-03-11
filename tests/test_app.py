import base64
import hashlib
import hmac
from importlib import metadata
from pathlib import Path
import platform
import tomllib

from fastapi import Request
from fastapi.testclient import TestClient

from dmguard.app import APP_VERSION, MAX_REQUEST_BODY_BYTES
from dmguard.config import AppConfig


def build_config(*, debug: bool = False) -> AppConfig:
    return AppConfig(
        debug=debug,
        log_level="INFO",
        public_hostname="dmguard.duckdns.org",
        acme_email="ori@example.com",
    )


class StubSecretStore:
    def __init__(self, consumer_secret: str) -> None:
        self._consumer_secret = consumer_secret

    def get(self, key: str) -> str:
        if key != "x_consumer_secret":
            raise AssertionError(f"Unexpected secret key: {key}")

        return self._consumer_secret


def expected_app_version() -> str:
    try:
        return metadata.version("x-dm-moderator")
    except metadata.PackageNotFoundError:
        with (Path(__file__).resolve().parents[1] / "pyproject.toml").open("rb") as fh:
            pyproject = tomllib.load(fh)

        return pyproject["project"]["version"]


def test_create_app_succeeds_without_db() -> None:
    from dmguard.app import create_app

    app = create_app(build_config())

    assert app is not None


def test_health_endpoint_returns_ok_payload() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_version_endpoint_returns_version_metadata() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config()))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": expected_app_version(),
        "python": platform.python_version(),
        "fastapi": metadata.version("fastapi"),
        "aiosqlite": metadata.version("aiosqlite"),
        "httpx": metadata.version("httpx"),
    }


def test_dep_version_returns_unknown_for_missing_package() -> None:
    from dmguard.app import _dep_version

    assert _dep_version("no-such-package-xyzzy") == "unknown"


def test_version_endpoint_caches_payload_at_app_creation(monkeypatch) -> None:
    import dmguard.app as app_module

    build_calls = 0
    cached_version_info = {
        "version": APP_VERSION,
        "python": "3.12.12",
        "fastapi": "1.0.0",
        "aiosqlite": "2.0.0",
        "httpx": "3.0.0",
    }

    def fake_build_version_info() -> dict[str, str]:
        nonlocal build_calls

        build_calls += 1
        return cached_version_info

    monkeypatch.setattr(app_module, "build_version_info", fake_build_version_info)

    client = TestClient(app_module.create_app(build_config()))

    first_response = client.get("/version")
    second_response = client.get("/version")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == cached_version_info
    assert second_response.json() == cached_version_info
    assert build_calls == 1


def test_crc_endpoint_returns_expected_response_token() -> None:
    from dmguard.app import create_app

    crc_token = "challenge-token"
    consumer_secret = "consumer-secret"
    client = TestClient(create_app(build_config(), StubSecretStore(consumer_secret)))

    response = client.get("/webhooks/x", params={"crc_token": crc_token})

    expected_digest = hmac.digest(
        consumer_secret.encode("utf-8"),
        crc_token.encode("utf-8"),
        hashlib.sha256,
    )
    expected_token = base64.b64encode(expected_digest).decode("utf-8")

    assert response.status_code == 200
    assert response.json() == {"response_token": f"sha256={expected_token}"}


def test_crc_endpoint_returns_400_when_crc_token_is_missing() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config(), StubSecretStore("consumer-secret")))

    response = client.get("/webhooks/x")

    assert response.status_code == 400


def test_non_debug_app_hides_docs_and_openapi() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config(debug=False)))

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_debug_app_exposes_docs_and_openapi() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config(debug=True)))

    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_request_body_limit_allows_exactly_one_megabyte() -> None:
    from dmguard.app import create_app

    app = create_app(build_config())

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    client = TestClient(app)

    response = client.post("/echo", content=b"x" * MAX_REQUEST_BODY_BYTES)

    assert response.status_code == 200
    assert response.json() == {"size": MAX_REQUEST_BODY_BYTES}


def test_request_body_limit_rejects_payloads_over_one_megabyte() -> None:
    from dmguard.app import create_app

    app = create_app(build_config())

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    client = TestClient(app)

    response = client.post("/echo", content=b"x" * (MAX_REQUEST_BODY_BYTES + 1))

    assert response.status_code == 413
