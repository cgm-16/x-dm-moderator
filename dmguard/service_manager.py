from collections.abc import Mapping
from pathlib import Path
import json
import subprocess
import sys

from dmguard.paths import PROGRAM_DATA_DIR


SERVY_CLI_PATH = Path("C:/Program Files/Servy/servy-cli.exe")
SERVICES_DIR = PROGRAM_DATA_DIR / "services"
TRAEFIK_SERVICE_DEF_PATH = SERVICES_DIR / "traefik-service.json"
DMGUARD_SERVICE_DEF_PATH = SERVICES_DIR / "dmguard-service.json"


def write_service_definition(path: Path, definition: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(definition), indent=2), encoding="utf-8")


def install_service(definition: Mapping[str, object]) -> None:
    if not sys.platform.startswith("win"):
        return

    command = [
        str(SERVY_CLI_PATH),
        "install",
        "--quiet",
        "--name",
        str(definition["name"]),
        "--displayName",
        str(definition["displayName"]),
        "--description",
        str(definition["description"]),
        "--path",
        str(definition["path"]),
        "--startupDir",
        str(definition["startupDir"]),
        "--startupType",
        str(definition["startupType"]),
        "--stdout",
        str(definition["stdout"]),
        "--stderr",
        str(definition["stderr"]),
    ]

    params = definition.get("params")
    if isinstance(params, str) and params:
        command.append(f"--params={params}")

    deps = definition.get("deps")
    if isinstance(deps, list) and deps:
        command.append(f"--deps={'; '.join(str(dep) for dep in deps)}")

    _run_servy_command(command)


def start_service(service_name: str) -> None:
    if not sys.platform.startswith("win"):
        return

    _run_servy_command(
        [
            str(SERVY_CLI_PATH),
            "start",
            "--quiet",
            "--name",
            service_name,
        ]
    )


def get_service_status(service_name: str) -> str:
    if not sys.platform.startswith("win"):
        return "Running"

    completed = _run_servy_command(
        [
            str(SERVY_CLI_PATH),
            "status",
            "--quiet",
            "--name",
            service_name,
        ]
    )
    status_lines = [
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    ]
    last = status_lines[-1] if status_lines else ""
    # servy-cli outputs "Service status: <Status>" — extract the value after the colon
    return last.split(":")[-1].strip() if ":" in last else last


def _run_servy_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stdout = exc.output.strip() if exc.output else "(no stdout)"
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        raise RuntimeError(
            f"servy-cli exited {exc.returncode} | stdout: {stdout} | stderr: {stderr}"
        ) from exc


__all__ = [
    "DMGUARD_SERVICE_DEF_PATH",
    "SERVICES_DIR",
    "SERVY_CLI_PATH",
    "TRAEFIK_SERVICE_DEF_PATH",
    "get_service_status",
    "install_service",
    "start_service",
    "write_service_definition",
]
