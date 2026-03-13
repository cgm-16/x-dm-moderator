from pathlib import Path
import json


def write_classifier_input(
    tmp_path: Path,
    *,
    mode: str,
    files: list[str],
    policy: str = "O2_violence_harm_cruelty",
) -> Path:
    input_path = tmp_path / "classifier-input.json"
    input_path.write_text(
        json.dumps({"mode": mode, "files": files, "policy": policy}),
        encoding="utf-8",
    )
    return input_path


def test_classifier_fake_force_safe_writes_valid_json_to_stdout(
    tmp_path: Path, capsys
) -> None:
    from dmguard.classifier_contract import ClassifierResponse
    from dmguard.classifier_fake import main

    input_path = write_classifier_input(tmp_path, mode="image", files=["image.jpg"])

    exit_code = main([str(input_path), "--force-safe"])

    captured = capsys.readouterr()
    response = ClassifierResponse.model_validate_json(captured.out)

    assert exit_code == 0
    assert response.rating == "safe"
    assert response.category == "NA: None applying"
    assert response.rationale == "Forced safe for testing"
    assert response.trigger_frame_index is None


def test_classifier_fake_force_unsafe_video_returns_trigger_frame_index(
    tmp_path: Path, capsys
) -> None:
    from dmguard.classifier_contract import ClassifierResponse
    from dmguard.classifier_fake import main

    input_path = write_classifier_input(
        tmp_path,
        mode="video",
        files=["frame-1.jpg", "frame-2.jpg"],
    )

    exit_code = main([str(input_path), "--force-unsafe"])

    captured = capsys.readouterr()
    response = ClassifierResponse.model_validate_json(captured.out)

    assert exit_code == 0
    assert response.rating == "unsafe"
    assert response.category == "O2: Violence, Harm, or Cruelty"
    assert response.rationale == "Forced unsafe for testing"
    assert response.trigger_frame_index == 0


def test_classifier_fake_force_unsafe_image_omits_trigger_frame_index(
    tmp_path: Path, capsys
) -> None:
    from dmguard.classifier_contract import ClassifierResponse
    from dmguard.classifier_fake import main

    input_path = write_classifier_input(tmp_path, mode="image", files=["image.jpg"])

    exit_code = main([str(input_path), "--force-unsafe"])

    captured = capsys.readouterr()
    response = ClassifierResponse.model_validate_json(captured.out)

    assert exit_code == 0
    assert response.rating == "unsafe"
    assert response.trigger_frame_index is None
