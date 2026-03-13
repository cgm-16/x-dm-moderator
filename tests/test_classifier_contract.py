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
            "policy": "O2_violence_harm_cruelty",
        },
    )

    request = ClassifierRequest.model_validate_json(
        input_path.read_text(encoding="utf-8")
    )

    assert request.mode == "image"
    assert request.files == ["frame-1.jpg"]
    assert request.policy == "O2_violence_harm_cruelty"


def test_classifier_request_rejects_empty_files_list(tmp_path: Path) -> None:
    from dmguard.classifier_contract import ClassifierRequest

    input_path = write_classifier_input(
        tmp_path,
        {
            "mode": "video",
            "files": [],
            "policy": "O2_violence_harm_cruelty",
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
                "rating": "safe",
                "category": "NA: None applying",
                "rationale": "test",
            }
        )

    assert "policy" in str(exc_info.value)
