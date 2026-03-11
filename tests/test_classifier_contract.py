from pathlib import Path
import json

import pytest
from pydantic import ValidationError


def write_classifier_input(tmp_path: Path, payload: dict[str, object]) -> Path:
    input_path = tmp_path / "classifier-input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    return input_path


def test_classifier_request_parses_valid_image_payload(tmp_path: Path) -> None:
    from dmguard.classifier_contract import ClassifierRequest

    input_path = write_classifier_input(
        tmp_path,
        {
            "mode": "image",
            "files": ["frame-1.jpg"],
            "policy": "violence_gore",
        },
    )

    request = ClassifierRequest.model_validate_json(
        input_path.read_text(encoding="utf-8")
    )

    assert request.mode == "image"
    assert request.files == ["frame-1.jpg"]
    assert request.policy == "violence_gore"


def test_classifier_request_rejects_empty_files_list(tmp_path: Path) -> None:
    from dmguard.classifier_contract import ClassifierRequest

    input_path = write_classifier_input(
        tmp_path,
        {
            "mode": "video",
            "files": [],
            "policy": "violence_gore",
        },
    )

    with pytest.raises(ValidationError) as exc_info:
        ClassifierRequest.model_validate_json(input_path.read_text(encoding="utf-8"))

    assert "files" in str(exc_info.value)


def test_classifier_response_requires_known_policy() -> None:
    from dmguard.classifier_contract import ClassifierResponse

    with pytest.raises(ValidationError) as exc_info:
        ClassifierResponse.model_validate(
            {
                "policy": "unknown_policy",
                "yes_prob": 0.5,
                "trigger_frame_index": None,
                "trigger_time_sec": None,
            }
        )

    assert "policy" in str(exc_info.value)
