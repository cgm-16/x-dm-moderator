from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
import hashlib
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
    effective_args: dict[str, str | int | float | bool | None]
    stages: dict[str, StageStatus]
    updated_at: str


SETUP_STAGE_ORDER = (
    "preflight",
    "local_config",
    "x_auth",
    "duckdns",
    "traefik",
    "tls",
    "app_service",
    "public_reachability",
    "warmup",
    "x_webhook",
)
_STAGE_INDEX = {stage_name: index for index, stage_name in enumerate(SETUP_STAGE_ORDER)}
_ARG_EARLIEST_STAGE = {
    "debug": "preflight",
    "log_level": "local_config",
    "port": "local_config",
    "host": "local_config",
    "debug_dashboard_port": "traefik",
    "public_hostname": "local_config",
    "acme_email": "tls",
}


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


def compute_args_hash(args: dict[str, str | int | float | bool | None]) -> str:
    encoded_args = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded_args.encode("utf-8")).hexdigest()


def invalidate_changed_stages(
    state: SetupState, new_args: dict[str, str | int | float | bool | None]
) -> list[str]:
    if state.effective_args == new_args:
        return []

    changed_args = _changed_arg_names(state.effective_args, new_args)
    invalidated_stages = _invalidated_stage_names(state.stages, changed_args)

    for stage_name in invalidated_stages:
        state.stages[stage_name] = StageStatus(
            status="pending",
            started_at=None,
            finished_at=None,
            artifacts=[],
        )

    state.effective_args = dict(new_args)
    return invalidated_stages


def describe_verbose_stage_changes(
    state: SetupState, new_args: dict[str, str | int | float | bool | None]
) -> list[str]:
    changed_args = _changed_arg_names(state.effective_args, new_args)
    invalidated_stages = set(_invalidated_stage_names(state.stages, changed_args))
    changed_arg_list = ", ".join(changed_args)
    messages: list[str] = []

    for stage_name in _ordered_stage_names(state.stages):
        stage = state.stages[stage_name]
        if stage_name in invalidated_stages:
            messages.append(
                f"stage {stage_name}: invalidated because {changed_arg_list} changed"
            )
        elif stage.status == "done":
            messages.append(f"stage {stage_name}: already done, skipping")

    return messages


def _changed_arg_names(
    previous_args: dict[str, str | int | float | bool | None],
    new_args: dict[str, str | int | float | bool | None],
) -> list[str]:
    return sorted(
        arg_name
        for arg_name in set(previous_args) | set(new_args)
        if previous_args.get(arg_name) != new_args.get(arg_name)
    )


def _invalidated_stage_names(
    stages: dict[str, StageStatus], changed_args: list[str]
) -> list[str]:
    if not changed_args:
        return []

    earliest_stage_name = min(
        (_ARG_EARLIEST_STAGE.get(arg_name, "preflight") for arg_name in changed_args),
        key=lambda stage_name: _STAGE_INDEX[stage_name],
    )
    earliest_index = _STAGE_INDEX[earliest_stage_name]

    return [
        stage_name
        for stage_name in _ordered_stage_names(stages)
        if _STAGE_INDEX.get(stage_name, len(SETUP_STAGE_ORDER)) >= earliest_index
    ]


def _ordered_stage_names(stages: dict[str, StageStatus]) -> list[str]:
    ordered_stage_names = [
        stage_name for stage_name in SETUP_STAGE_ORDER if stage_name in stages
    ]
    ordered_stage_names.extend(
        stage_name for stage_name in stages if stage_name not in _STAGE_INDEX
    )
    return ordered_stage_names


__all__ = [
    "SETUP_STAGE_ORDER",
    "SetupState",
    "StageStatus",
    "compute_args_hash",
    "describe_verbose_stage_changes",
    "invalidate_changed_stages",
    "load_setup_state",
    "save_setup_state",
]
