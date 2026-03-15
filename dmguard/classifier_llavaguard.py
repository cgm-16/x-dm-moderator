from argparse import ArgumentParser
from functools import lru_cache
from pathlib import Path
from typing import Sequence
import json
import sys

import torch
from transformers import AutoProcessor, LlavaOnevisionForConditionalGeneration
from transformers.image_utils import load_image

from dmguard.classifier_contract import (
    ClassifierRequest,
    ClassifierResponse,
    load_classifier_request,
)
from dmguard.secrets import FileSecretStore, SecretStore


MODEL_ID = "AIML-TUDA/LlavaGuard-v1.2-0.5B-OV-hf"
_PROMPT = """
Assess the image for safety using the LlavaGuard taxonomy.
Consider these categories:
- O1: Sexual content
- O2: Violence, Harm, or Cruelty
- O3: Criminal Planning or Weapons
- O4: Controlled or Illegal Substances
- O5: Suicide or Self-Harm
- O6: Hate or Harassment
- O7: Exploitation or Abuse
- O8: Privacy or Sensitive Personal Data
- O9: Regulated Goods or Services

Return only compact JSON with keys:
- rating: Safe or Unsafe
- category: the best matching category label, or "NA: None applying"
- rationale: one short sentence
""".strip()


def build_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("input_path", type=Path)
    return parser


def parse_llavaguard_output(
    output_text: str,
    policy: str,
) -> ClassifierResponse:
    start = output_text.find("{")
    end = output_text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LlavaGuard output did not contain JSON")

    payload = json.loads(output_text[start : end + 1])
    rating = str(payload["rating"]).strip().lower()
    if rating not in {"safe", "unsafe"}:
        raise ValueError(f"Unsupported LlavaGuard rating: {payload['rating']}")

    category = str(payload["category"]).strip()
    rationale = str(payload["rationale"]).strip()
    if not category:
        raise ValueError("LlavaGuard output must include a category")
    if not rationale:
        raise ValueError("LlavaGuard output must include a rationale")

    return ClassifierResponse(
        policy=policy,
        rating=rating,
        category=category,
        rationale=rationale,
    )


def load_llavaguard_runtime(
    secret_store: SecretStore | None = None,
):
    if not torch.cuda.is_available():
        raise RuntimeError("LlavaGuard runtime requires CUDA")

    store = secret_store or FileSecretStore()
    hf_token = store.get("hf_token")
    return _load_cached_runtime(hf_token)


@lru_cache(maxsize=1)
def _load_cached_runtime(hf_token: str):
    processor = AutoProcessor.from_pretrained(MODEL_ID, token=hf_token)
    model = LlavaOnevisionForConditionalGeneration.from_pretrained(
        MODEL_ID,
        token=hf_token,
        torch_dtype=torch.float16,
    )
    model.to("cuda")
    model.eval()
    return processor, model


def classify_image(
    path: Path,
    policy: str,
    processor,
    model,
) -> ClassifierResponse:
    conversation = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image"},
            ],
        }
    ]
    prompt = processor.apply_chat_template(conversation, add_generation_prompt=True)
    inputs = processor(
        text=prompt,
        images=load_image(str(path)),
        return_tensors="pt",
    ).to(model.device)

    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=200)

    prompt_length = inputs["input_ids"].shape[-1]
    output_text = processor.decode(
        output_ids[0][prompt_length:],
        skip_special_tokens=True,
    )
    return parse_llavaguard_output(output_text, policy)


def classify_request(
    request: ClassifierRequest,
    *,
    secret_store: SecretStore | None = None,
) -> ClassifierResponse:
    processor, model = load_llavaguard_runtime(secret_store=secret_store)
    safe_response: ClassifierResponse | None = None

    for index, file_path in enumerate(request.files):
        response = classify_image(Path(file_path), request.policy, processor, model)
        if response.rating == "unsafe":
            if request.mode == "video":
                return response.model_copy(update={"trigger_frame_index": index})
            return response

        if safe_response is None:
            safe_response = response

    if safe_response is None:
        raise ValueError("LlavaGuard request must include at least one file")

    return safe_response


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request = load_classifier_request(args.input_path)
    response = classify_request(request)
    print(response.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
