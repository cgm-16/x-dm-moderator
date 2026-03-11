from pathlib import Path
import logging
import sys
import textwrap
import time

import pytest


def clear_logger(name: str) -> None:
    logger = logging.getLogger(name)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(logging.NOTSET)
    logger.propagate = True


@pytest.fixture(autouse=True)
def reset_classifier_logger() -> None:
    clear_logger("classifier")

    yield

    clear_logger("classifier")


def configure_classifier_logger(log_path: Path) -> None:
    logger = logging.getLogger("classifier")
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def flush_classifier_logger() -> None:
    for handler in logging.getLogger("classifier").handlers:
        handler.flush()


def write_script(tmp_path: Path, name: str, body: str) -> Path:
    script_path = tmp_path / name
    script_path.write_text(textwrap.dedent(body), encoding="utf-8")
    return script_path


def read_input_path(marker_path: Path) -> Path:
    return Path(marker_path.read_text(encoding="utf-8").strip())


def test_run_classifier_returns_parsed_response_logs_stderr_and_cleans_up_input_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard.classifier_contract import ClassifierResponse
    from dmguard import classifier_runner

    tmp_dir = tmp_path / "runner-tmp"
    log_path = tmp_path / "classifier.log"
    marker_path = tmp_path / "input-path.txt"
    script_path = write_script(
        tmp_path,
        "classifier_success.py",
        """
        from pathlib import Path
        import json
        import sys

        marker_path = Path(sys.argv[1])
        input_path = Path(sys.argv[2])
        marker_path.write_text(str(input_path), encoding="utf-8")

        request = json.loads(input_path.read_text(encoding="utf-8"))
        sys.stderr.write("classifier warning\\n")
        print(
            json.dumps(
                {
                    "policy": request["policy"],
                    "yes_prob": 0.01,
                    "trigger_frame_index": None,
                    "trigger_time_sec": None,
                }
            )
        )
        """,
    )

    monkeypatch.setattr(classifier_runner, "TMP_DIR", tmp_dir)
    configure_classifier_logger(log_path)

    response = classifier_runner.run_classifier(
        {
            "mode": "image",
            "files": ["frame-1.jpg"],
            "policy": "violence_gore",
        },
        [sys.executable, str(script_path), str(marker_path)],
    )

    flush_classifier_logger()
    input_path = read_input_path(marker_path)

    assert response == ClassifierResponse(
        policy="violence_gore",
        yes_prob=0.01,
    )
    assert not input_path.exists()
    assert "classifier warning" in log_path.read_text(encoding="utf-8")


def test_run_classifier_raises_error_and_cleans_up_input_file_on_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import classifier_runner

    tmp_dir = tmp_path / "runner-tmp"
    log_path = tmp_path / "classifier.log"
    marker_path = tmp_path / "input-path.txt"
    script_path = write_script(
        tmp_path,
        "classifier_fail.py",
        """
        from pathlib import Path
        import sys

        marker_path = Path(sys.argv[1])
        input_path = Path(sys.argv[2])
        marker_path.write_text(str(input_path), encoding="utf-8")
        sys.stderr.write("classifier failed\\n")
        raise SystemExit(3)
        """,
    )

    monkeypatch.setattr(classifier_runner, "TMP_DIR", tmp_dir)
    configure_classifier_logger(log_path)

    with pytest.raises(classifier_runner.ClassifierError) as exc_info:
        classifier_runner.run_classifier(
            {
                "mode": "image",
                "files": ["frame-1.jpg"],
                "policy": "violence_gore",
            },
            [sys.executable, str(script_path), str(marker_path)],
        )

    flush_classifier_logger()
    input_path = read_input_path(marker_path)

    assert str(exc_info.value) == "classifier failed"
    assert not input_path.exists()
    assert "classifier failed" in log_path.read_text(encoding="utf-8")


def test_run_classifier_kills_timed_out_process_and_cleans_up_input_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import classifier_runner

    tmp_dir = tmp_path / "runner-tmp"
    marker_path = tmp_path / "input-path.txt"
    completed_path = tmp_path / "completed.txt"
    script_path = write_script(
        tmp_path,
        "classifier_timeout.py",
        """
        from pathlib import Path
        import sys
        import time

        marker_path = Path(sys.argv[1])
        completed_path = Path(sys.argv[2])
        input_path = Path(sys.argv[3])
        marker_path.write_text(str(input_path), encoding="utf-8")
        time.sleep(5)
        completed_path.write_text("done", encoding="utf-8")
        """,
    )

    monkeypatch.setattr(classifier_runner, "TMP_DIR", tmp_dir)
    monkeypatch.setattr(classifier_runner, "CLASSIFIER_TIMEOUT_SECONDS", 0.1)

    start = time.monotonic()
    with pytest.raises(classifier_runner.ClassifierTimeoutError):
        classifier_runner.run_classifier(
            {
                "mode": "video",
                "files": ["frame-1.jpg"],
                "policy": "violence_gore",
            },
            [sys.executable, str(script_path), str(marker_path), str(completed_path)],
        )

    elapsed = time.monotonic() - start
    input_path = read_input_path(marker_path)

    time.sleep(0.2)

    assert elapsed < 2
    assert not input_path.exists()
    assert not completed_path.exists()


def test_run_classifier_raises_classifier_error_on_invalid_json_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import classifier_runner

    tmp_dir = tmp_path / "runner-tmp"
    marker_path = tmp_path / "input-path.txt"
    script_path = write_script(
        tmp_path,
        "classifier_bad_output.py",
        """
        from pathlib import Path
        import sys

        marker_path = Path(sys.argv[1])
        input_path = Path(sys.argv[2])
        marker_path.write_text(str(input_path), encoding="utf-8")
        print("this is not valid json")
        """,
    )

    monkeypatch.setattr(classifier_runner, "TMP_DIR", tmp_dir)

    with pytest.raises(classifier_runner.ClassifierError):
        classifier_runner.run_classifier(
            {
                "mode": "image",
                "files": ["frame-1.jpg"],
                "policy": "violence_gore",
            },
            [sys.executable, str(script_path), str(marker_path)],
        )

    input_path = read_input_path(marker_path)
    assert not input_path.exists()
