import logging
from pathlib import Path

import pytest

from dmguard.config import AppConfig


def build_config(*, log_level: str = "INFO") -> AppConfig:
    return AppConfig(
        debug=False,
        log_level=log_level,
        public_hostname="dmguard.duckdns.org",
        acme_email="ori@example.com",
    )


def clear_logger(name: str) -> None:
    logger = logging.getLogger(name)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(logging.NOTSET)
    logger.propagate = True


@pytest.fixture(autouse=True)
def reset_named_loggers() -> None:
    clear_logger("dmguard")
    clear_logger("classifier")

    yield

    clear_logger("dmguard")
    clear_logger("classifier")


def flush_logger_handlers(name: str) -> None:
    for handler in logging.getLogger(name).handlers:
        handler.flush()


def test_setup_logging_creates_log_files_and_named_loggers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.logging_setup as logging_setup

    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(logging_setup, "LOGS_DIR", logs_dir)

    logging_setup.setup_logging(build_config())

    assert logs_dir.is_dir()
    assert (logs_dir / "dmguard.log").exists()
    assert (logs_dir / "classifier.log").exists()
    assert logging.getLogger("dmguard").name == "dmguard"
    assert logging.getLogger("classifier").name == "classifier"


def test_setup_logging_applies_configured_log_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.logging_setup as logging_setup

    monkeypatch.setattr(logging_setup, "LOGS_DIR", tmp_path / "logs")

    logging_setup.setup_logging(build_config(log_level="WARNING"))

    assert logging.getLogger("dmguard").level == logging.WARNING
    assert logging.getLogger("classifier").level == logging.WARNING


def test_setup_logging_routes_messages_to_separate_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.logging_setup as logging_setup

    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(logging_setup, "LOGS_DIR", logs_dir)

    logging_setup.setup_logging(build_config())

    dmguard_logger = logging.getLogger("dmguard")
    classifier_logger = logging.getLogger("classifier")

    dmguard_logger.info("dmguard message")
    classifier_logger.info("classifier message")

    flush_logger_handlers("dmguard")
    flush_logger_handlers("classifier")

    dmguard_log = (logs_dir / "dmguard.log").read_text(encoding="utf-8")
    classifier_log = (logs_dir / "classifier.log").read_text(encoding="utf-8")

    assert "dmguard message" in dmguard_log
    assert "classifier message" not in dmguard_log
    assert "classifier message" in classifier_log
    assert "dmguard message" not in classifier_log


def test_setup_logging_replaces_existing_handlers_on_repeat_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import dmguard.logging_setup as logging_setup

    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(logging_setup, "LOGS_DIR", logs_dir)

    logging_setup.setup_logging(build_config())
    logging_setup.setup_logging(build_config())

    dmguard_logger = logging.getLogger("dmguard")
    classifier_logger = logging.getLogger("classifier")

    assert len(dmguard_logger.handlers) == 1
    assert len(classifier_logger.handlers) == 1

    dmguard_logger.info("written once")
    flush_logger_handlers("dmguard")

    dmguard_log = (logs_dir / "dmguard.log").read_text(encoding="utf-8")

    assert dmguard_log.count("written once") == 1
