from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os
import sys


WINDOWS_PROGRAM_FILES_DIR = Path("C:/Program Files/XDMModerator")
WINDOWS_PROGRAM_DATA_DIR = Path("C:/ProgramData/XDMModerator")
NON_WINDOWS_APP_ROOT_ENV = "DMGUARD_APP_ROOT"
NON_WINDOWS_DATA_ROOT_ENV = "DMGUARD_DATA_ROOT"


@dataclass(frozen=True)
class ResolvedPaths:
    program_files_dir: Path
    program_data_dir: Path
    db_path: Path
    config_path: Path
    secrets_path: Path
    logs_dir: Path
    tmp_dir: Path


def _resolve_non_windows_roots(env: Mapping[str, str]) -> tuple[Path, Path]:
    app_root = env.get(NON_WINDOWS_APP_ROOT_ENV)
    data_root = env.get(NON_WINDOWS_DATA_ROOT_ENV)
    missing = []

    if not app_root:
        missing.append(NON_WINDOWS_APP_ROOT_ENV)

    if not data_root:
        missing.append(NON_WINDOWS_DATA_ROOT_ENV)

    if missing:
        raise ValueError(
            "Non-Windows path resolution requires "
            f"{NON_WINDOWS_APP_ROOT_ENV} and {NON_WINDOWS_DATA_ROOT_ENV}; "
            f"missing: {', '.join(missing)}"
        )

    return Path(app_root), Path(data_root)


def resolve_paths(
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedPaths:
    current_platform = platform or sys.platform
    current_env = os.environ if env is None else env

    if current_platform.startswith("win"):
        program_files_dir = WINDOWS_PROGRAM_FILES_DIR
        program_data_dir = WINDOWS_PROGRAM_DATA_DIR
    else:
        program_files_dir, program_data_dir = _resolve_non_windows_roots(current_env)

    return ResolvedPaths(
        program_files_dir=program_files_dir,
        program_data_dir=program_data_dir,
        db_path=program_data_dir / "state.db",
        config_path=program_data_dir / "config.yaml",
        secrets_path=program_data_dir / "secrets.bin",
        logs_dir=program_data_dir / "logs",
        tmp_dir=program_data_dir / "tmp",
    )


_RESOLVED_PATHS = resolve_paths()

PROGRAM_FILES_DIR = _RESOLVED_PATHS.program_files_dir
PROGRAM_DATA_DIR = _RESOLVED_PATHS.program_data_dir
DB_PATH = _RESOLVED_PATHS.db_path
CONFIG_PATH = _RESOLVED_PATHS.config_path
SECRETS_PATH = _RESOLVED_PATHS.secrets_path
LOGS_DIR = _RESOLVED_PATHS.logs_dir
TMP_DIR = _RESOLVED_PATHS.tmp_dir


__all__ = [
    "CONFIG_PATH",
    "DB_PATH",
    "LOGS_DIR",
    "PROGRAM_DATA_DIR",
    "PROGRAM_FILES_DIR",
    "ResolvedPaths",
    "SECRETS_PATH",
    "TMP_DIR",
    "resolve_paths",
]
