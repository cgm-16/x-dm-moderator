from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


ClassifierMode = Literal["image", "video"]
ClassifierPolicy = Literal["O2_violence_harm_cruelty"]


class ClassifierRequest(BaseModel):
    mode: ClassifierMode
    files: list[str] = Field(min_length=1)
    policy: ClassifierPolicy


class ClassifierResponse(BaseModel):
    policy: ClassifierPolicy
    rating: Literal["safe", "unsafe"]
    category: str
    rationale: str
    trigger_frame_index: int | None = None


def load_classifier_request(path: Path) -> ClassifierRequest:
    return ClassifierRequest.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = [
    "ClassifierMode",
    "ClassifierPolicy",
    "ClassifierRequest",
    "ClassifierResponse",
    "load_classifier_request",
]
