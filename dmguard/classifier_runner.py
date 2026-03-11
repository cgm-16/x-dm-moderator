from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Sequence
import json
import logging
import os
import subprocess

from dmguard.classifier_contract import ClassifierResponse
from dmguard.paths import TMP_DIR


CLASSIFIER_TIMEOUT_SECONDS = 180.0


class ClassifierError(RuntimeError):
    pass


class ClassifierTimeoutError(TimeoutError):
    pass


def run_classifier(
    input_data: dict[str, object],
    classifier_cmd: Sequence[str],
) -> ClassifierResponse:
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=TMP_DIR,
        prefix="classifier-input-",
        suffix=".json",
        delete=False,
    ) as temp_file:
        temp_file.write(json.dumps(input_data))
        input_path = Path(temp_file.name)

    process = None

    try:
        process = subprocess.Popen(
            [*classifier_cmd, str(input_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            stdout_text, stderr_text = process.communicate(
                timeout=CLASSIFIER_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired as error:
            process.kill()
            stdout_text, stderr_text = process.communicate()
            _log_stderr(stderr_text)
            raise ClassifierTimeoutError(
                f"Classifier timed out after {CLASSIFIER_TIMEOUT_SECONDS} seconds"
            ) from error

        _log_stderr(stderr_text)

        if process.returncode != 0:
            raise ClassifierError(stderr_text.strip() or "Classifier process failed")

        try:
            return ClassifierResponse.model_validate_json(stdout_text)
        except Exception as exc:
            raise ClassifierError(
                f"Classifier returned invalid response: {exc}"
            ) from exc
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()

        if input_path.exists():
            os.unlink(input_path)


def _log_stderr(stderr_text: str) -> None:
    message = stderr_text.strip()

    if message:
        logging.getLogger("classifier").warning(message)


__all__ = [
    "CLASSIFIER_TIMEOUT_SECONDS",
    "ClassifierError",
    "ClassifierTimeoutError",
    "run_classifier",
]
