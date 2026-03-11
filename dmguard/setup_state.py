from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
import json
import os

from pydantic import BaseModel


class StageStatus(BaseModel):
    status: Literal["pending", "running", "done", "failed", "skipped"]
    started_at: str | None
    finished_at: str | None
    artifacts: list[str]


class SetupState(BaseModel):
    last_command: str
    effective_args: dict[str, object]
    stages: dict[str, StageStatus]
    updated_at: str


def load_setup_state(path: Path) -> SetupState | None:
    if not path.exists():
        return None

    with path.open(encoding="utf-8") as state_file:
        raw_state = json.load(state_file)

    return SetupState.model_validate(raw_state)


def save_setup_state(state: SetupState, path: Path) -> None:
    payload = json.dumps(state.model_dump(mode="json"), indent=2)

    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_file.write(payload)
        temp_path = Path(temp_file.name)

    os.replace(temp_path, path)


__all__ = ["SetupState", "StageStatus", "load_setup_state", "save_setup_state"]
