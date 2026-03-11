from pathlib import Path

import pytest
from pydantic import ValidationError


def write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_load_app_config_parses_valid_yaml(tmp_path: Path) -> None:
    from dmguard.config import AppConfig, load_app_config

    config_path = write_config(
        tmp_path,
        """
debug: true
log_level: INFO
port: 9000
host: 0.0.0.0
debug_dashboard_port: 9001
public_hostname: dmguard.duckdns.org
acme_email: ori@example.com
""".strip(),
    )

    config = load_app_config(config_path)

    assert config == AppConfig(
        debug=True,
        log_level="INFO",
        port=9000,
        host="0.0.0.0",
        debug_dashboard_port=9001,
        public_hostname="dmguard.duckdns.org",
        acme_email="ori@example.com",
    )


def test_load_app_config_applies_defaults_for_optional_fields(tmp_path: Path) -> None:
    from dmguard.config import load_app_config

    config_path = write_config(
        tmp_path,
        """
debug: false
log_level: WARNING
public_hostname: dmguard.duckdns.org
acme_email: ori@example.com
""".strip(),
    )

    config = load_app_config(config_path)

    assert config.port == 8080
    assert config.host == "127.0.0.1"
    assert config.debug_dashboard_port == 8081


def test_load_app_config_raises_validation_error_for_missing_required_field(
    tmp_path: Path,
) -> None:
    from dmguard.config import load_app_config

    config_path = write_config(
        tmp_path,
        """
debug: true
log_level: INFO
acme_email: ori@example.com
""".strip(),
    )

    with pytest.raises(ValidationError) as exc_info:
        load_app_config(config_path)

    assert "public_hostname" in str(exc_info.value)


def test_load_app_config_ignores_extra_fields(tmp_path: Path) -> None:
    from dmguard.config import load_app_config

    config_path = write_config(
        tmp_path,
        """
debug: true
log_level: INFO
public_hostname: dmguard.duckdns.org
acme_email: ori@example.com
unexpected: value
""".strip(),
    )

    config = load_app_config(config_path)

    assert "unexpected" not in config.model_dump()


def test_load_app_config_uses_default_config_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import config

    config_path = write_config(
        tmp_path,
        """
debug: true
log_level: INFO
public_hostname: dmguard.duckdns.org
acme_email: ori@example.com
""".strip(),
    )

    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    loaded = config.load_app_config()

    assert loaded.public_hostname == "dmguard.duckdns.org"
