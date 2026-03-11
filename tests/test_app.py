from fastapi import Request
from fastapi.testclient import TestClient

from dmguard.config import AppConfig


MAX_REQUEST_BODY_BYTES = 1_048_576


def build_config(*, debug: bool = False) -> AppConfig:
    return AppConfig(
        debug=debug,
        log_level="INFO",
        public_hostname="dmguard.duckdns.org",
        acme_email="ori@example.com",
    )


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


def test_version_endpoint_returns_stub_version() -> None:
    from dmguard.app import create_app

    client = TestClient(create_app(build_config()))

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"version": "0.1.0"}


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
