import re
from pathlib import Path

import dmguard.setup_logger as setup_logger


def test_setup_logger_appends_timestamped_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "setup.log"
    logger = setup_logger.SetupLogger(log_path)

    logger.log("starting setup")
    logger.log("finished setup")

    lines = log_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 starting setup$", lines[0]
    )
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 finished setup$", lines[1]
    )


def test_setup_logger_redacts_known_secret_values(tmp_path: Path) -> None:
    log_path = tmp_path / "setup.log"
    logger = setup_logger.SetupLogger(log_path)
    message = (
        'x_access_token=access-token password: "hunter2" '
        "hf_token: dGhpc0lzQVNlY3JldEJsb2I="
    )

    redacted = logger.redact(message)

    assert "access-token" not in redacted
    assert "hunter2" not in redacted
    assert "dGhpc0lzQVNlY3JldEJsb2I=" not in redacted
    assert "x_access_token=[REDACTED]" in redacted
    assert 'password: "[REDACTED]"' in redacted
    assert "hf_token: [REDACTED]" in redacted


def test_setup_logger_redacts_bearer_token_with_trailing_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "setup.log"
    logger = setup_logger.SetupLogger(log_path)
    message = "authorization: Bearer eyJhbGciOiJSUzI1NiJ9.payload.sig stage=preflight"

    redacted = logger.redact(message)

    assert "Bearer" not in redacted
    assert "eyJhbGciOiJSUzI1NiJ9.payload.sig" not in redacted
    assert "authorization: [REDACTED]" in redacted
    assert "stage=preflight" in redacted


def test_setup_logger_preserves_non_secret_content_verbatim(tmp_path: Path) -> None:
    log_path = tmp_path / "setup.log"
    logger = setup_logger.SetupLogger(log_path)
    message = (
        "stage=preflight checksum=dGhpc0lzTm90QVNlY3JldA== "
        "public_hostname=dmguard.duckdns.org"
    )

    assert logger.redact(message) == message

    logger.log(message)

    logged_message = (
        log_path.read_text(encoding="utf-8").splitlines()[0].partition(" ")[2]
    )

    assert logged_message == message
