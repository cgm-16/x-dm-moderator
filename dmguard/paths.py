from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os
import sys


WINDOWS_PROGRAM_FILES_DIR = Path("C:/Program Files/XDMModerator")
WINDOWS_PROGRAM_DATA_DIR = Path("C:/ProgramData/XDMModerator")


@dataclass(frozen=True)
class ResolvedPaths:
    program_files_dir: Path
    program_data_dir: Path
    db_path: Path
    config_path: Path
    secrets_path: Path
    logs_dir: Path
    tmp_dir: Path


def resolve_paths(
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedPaths:
    current_platform = platform or sys.platform
    current_env = env or os.environ

    program_files_dir = WINDOWS_PROGRAM_FILES_DIR
    program_data_dir = WINDOWS_PROGRAM_DATA_DIR

    if not current_platform.startswith("win"):
        app_root = current_env.get("DMGUARD_APP_ROOT")
        data_root = current_env.get("DMGUARD_DATA_ROOT")

        if app_root:
            program_files_dir = Path(app_root)

        if data_root:
            program_data_dir = Path(data_root)

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
