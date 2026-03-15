import pytest

from dmguard.config import AppConfig


def build_config() -> AppConfig:
    return AppConfig(
        debug=False,
        log_level="INFO",
        port=9090,
        host="0.0.0.0",
        debug_dashboard_port=8081,
        public_hostname="dmguard.duckdns.org",
        acme_email="ori@example.com",
    )


def test_main_loads_config_sets_up_logging_and_runs_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dmguard.__main__ as main_module

    config = build_config()
    app = object()
    calls: list[str | tuple[str, object, str, int]] = []

    def fake_load_app_config() -> AppConfig:
        calls.append("load_config")
        return config

    def fake_setup_logging(received_config: AppConfig) -> None:
        assert received_config is config
        calls.append("setup_logging")

    def fake_create_app(received_config: AppConfig):
        assert received_config is config
        calls.append("create_app")
        return app

    def fake_uvicorn_run(received_app, *, host: str, port: int) -> None:
        calls.append(("uvicorn.run", received_app, host, port))

    monkeypatch.setattr(main_module, "load_app_config", fake_load_app_config)
    monkeypatch.setattr(main_module, "setup_logging", fake_setup_logging)
    monkeypatch.setattr(main_module, "create_app", fake_create_app)
    monkeypatch.setattr(main_module.uvicorn, "run", fake_uvicorn_run)

    exit_code = main_module.main()

    assert exit_code == 0
    assert calls == [
        "load_config",
        "setup_logging",
        "create_app",
        ("uvicorn.run", app, "0.0.0.0", 9090),
    ]
