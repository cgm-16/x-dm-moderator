from pathlib import Path
from tempfile import NamedTemporaryFile
import os

import yaml

from dmguard.config import AppConfig
from dmguard.paths import LOGS_DIR, PROGRAM_DATA_DIR, PROGRAM_FILES_DIR


TRAEFIK_SERVICE_NAME = "XDMModeratorTraefik"
DMGUARD_SERVICE_NAME = "XDMModerator"
TRAEFIK_BINARY_PATH = PROGRAM_FILES_DIR / "traefik" / "traefik.exe"
TRAEFIK_STARTUP_DIR = TRAEFIK_BINARY_PATH.parent
TRAEFIK_STATIC_CONFIG_PATH = PROGRAM_DATA_DIR / "traefik" / "traefik-static.yml"
DMGUARD_BINARY_PATH = PROGRAM_FILES_DIR / "dmguard.exe"


class InvalidYamlError(ValueError):
    pass


def write_routes_atomically(content: str, target: Path) -> None:
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)

    try:
        parsed = yaml.safe_load(content)
        if parsed is not None and not isinstance(parsed, dict):
            raise InvalidYamlError("Routes YAML must parse to a mapping")
    except yaml.YAMLError as exc:
        _delete_temp_file(temp_path)
        raise InvalidYamlError("Routes YAML is not valid YAML") from exc
    except InvalidYamlError:
        _delete_temp_file(temp_path)
        raise

    os.replace(temp_path, target)


def generate_traefik_service_def(config: AppConfig) -> dict[str, str]:
    _ = config
    return {
        "name": TRAEFIK_SERVICE_NAME,
        "displayName": "XDMModerator Traefik",
        "description": "Traefik reverse proxy for XDMModerator",
        "path": str(TRAEFIK_BINARY_PATH),
        "startupDir": str(TRAEFIK_STARTUP_DIR),
        "params": f"--configFile={TRAEFIK_STATIC_CONFIG_PATH}",
        "startupType": "Automatic",
        "stdout": str(LOGS_DIR / "traefik-service.out.log"),
        "stderr": str(LOGS_DIR / "traefik-service.err.log"),
    }


def generate_dmguard_service_def(config: AppConfig) -> dict[str, str | list[str]]:
    _ = config
    return {
        "name": DMGUARD_SERVICE_NAME,
        "displayName": "XDMModerator",
        "description": "XDMModerator application service",
        "path": str(DMGUARD_BINARY_PATH),
        "startupDir": str(PROGRAM_FILES_DIR),
        "startupType": "Automatic",
        "stdout": str(LOGS_DIR / "dmguard-service.out.log"),
        "stderr": str(LOGS_DIR / "dmguard-service.err.log"),
        "deps": [TRAEFIK_SERVICE_NAME],
    }


def _delete_temp_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


__all__ = [
    "InvalidYamlError",
    "generate_dmguard_service_def",
    "generate_traefik_service_def",
    "write_routes_atomically",
]
