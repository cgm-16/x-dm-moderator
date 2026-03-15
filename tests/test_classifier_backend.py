import logging
from pathlib import Path

import pytest


def write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_load_runtime_classifier_falls_back_to_fake_on_missing_config(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from dmguard.classifier_backend import (
        FAKE_CLASSIFIER_BASE_CMD,
        load_runtime_classifier,
    )

    missing_path = tmp_path / "nonexistent.yaml"

    with caplog.at_level(logging.WARNING):
        cmd, backend = load_runtime_classifier(missing_path)

    assert cmd == FAKE_CLASSIFIER_BASE_CMD
    assert backend == "fake"
    assert any("nonexistent.yaml" in record.message for record in caplog.records)


def test_load_runtime_classifier_returns_configured_backend(tmp_path: Path) -> None:
    from dmguard.classifier_backend import (
        LLAVAGUARD_CLASSIFIER_BASE_CMD,
        load_runtime_classifier,
    )

    config_path = write_config(
        tmp_path,
        """
debug: false
log_level: INFO
classifier_backend: llavaguard
port: 8080
host: 127.0.0.1
debug_dashboard_port: 8081
public_hostname: test.duckdns.org
acme_email: test@example.com
""".strip(),
    )

    cmd, backend = load_runtime_classifier(config_path)

    assert cmd == LLAVAGUARD_CLASSIFIER_BASE_CMD
    assert backend == "llavaguard"
