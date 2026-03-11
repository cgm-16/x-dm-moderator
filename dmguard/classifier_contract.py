from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


ClassifierMode = Literal["image", "video"]
ClassifierPolicy = Literal["violence_gore"]


class ClassifierRequest(BaseModel):
    mode: ClassifierMode
    files: list[str] = Field(min_length=1)
    policy: ClassifierPolicy


class ClassifierResponse(BaseModel):
    policy: ClassifierPolicy
    yes_prob: float
    trigger_frame_index: int | None = None
    trigger_time_sec: float | None = None


def load_classifier_request(path: Path) -> ClassifierRequest:
    return ClassifierRequest.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = [
    "ClassifierMode",
    "ClassifierPolicy",
    "ClassifierRequest",
    "ClassifierResponse",
    "load_classifier_request",
]
