from pathlib import Path
import json

import pytest


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


def test_parse_llavaguard_output_parses_generated_json() -> None:
    from dmguard.classifier_llavaguard import parse_llavaguard_output

    response = parse_llavaguard_output(
        'assistant {"rating":"Unsafe","category":"O2: Violence, Harm, or Cruelty","rationale":"Depicts graphic harm"}',
        "O2_violence_harm_cruelty",
    )

    assert response.policy == "O2_violence_harm_cruelty"
    assert response.rating == "unsafe"
    assert response.category == "O2: Violence, Harm, or Cruelty"
    assert response.rationale == "Depicts graphic harm"
    assert response.trigger_frame_index is None


def test_parse_llavaguard_output_rejects_text_without_json() -> None:
    from dmguard.classifier_llavaguard import parse_llavaguard_output

    with pytest.raises(ValueError, match="JSON"):
        parse_llavaguard_output("plain text response", "O2_violence_harm_cruelty")


def test_load_llavaguard_runtime_requires_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dmguard.classifier_llavaguard as module

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()
        float16 = "float16"

    monkeypatch.setattr(module, "torch", FakeTorch)

    with pytest.raises(RuntimeError, match="CUDA"):
        module.load_llavaguard_runtime()


def test_classify_request_sets_trigger_frame_index_for_unsafe_video_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard.classifier_contract import ClassifierRequest, ClassifierResponse
    import dmguard.classifier_llavaguard as module

    responses = iter(
        [
            ClassifierResponse(
                policy="O2_violence_harm_cruelty",
                rating="safe",
                category="NA: None applying",
                rationale="frame 0 clear",
            ),
            ClassifierResponse(
                policy="O2_violence_harm_cruelty",
                rating="unsafe",
                category="O2: Violence, Harm, or Cruelty",
                rationale="frame 1 unsafe",
            ),
        ]
    )

    monkeypatch.setattr(
        module,
        "load_llavaguard_runtime",
        lambda secret_store=None: ("processor", "model"),
    )
    monkeypatch.setattr(
        module,
        "classify_image",
        lambda path, policy, processor, model: next(responses),
    )

    response = module.classify_request(
        ClassifierRequest(
            mode="video",
            files=["frame-0.jpg", "frame-1.jpg"],
            policy="O2_violence_harm_cruelty",
        )
    )

    assert response.rating == "unsafe"
    assert response.trigger_frame_index == 1


def test_main_writes_classifier_response_json(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard.classifier_contract import ClassifierResponse
    import dmguard.classifier_llavaguard as module

    input_path = write_classifier_input(tmp_path, mode="image", files=["image.jpg"])
    expected = ClassifierResponse(
        policy="O2_violence_harm_cruelty",
        rating="safe",
        category="NA: None applying",
        rationale="No violence",
    )

    monkeypatch.setattr(module, "classify_request", lambda request: expected)

    exit_code = module.main([str(input_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert ClassifierResponse.model_validate_json(captured.out) == expected
