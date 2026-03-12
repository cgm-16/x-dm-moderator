import asyncio
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
import getpass
import json
import shutil
import socket
import sys

import httpx
import yaml

from dmguard.classifier_runner import run_classifier
from dmguard.db import get_connection
from dmguard.paths import CONFIG_PATH, DB_PATH, PROGRAM_DATA_DIR, SECRETS_PATH
from dmguard.repo_senders import (
    delete_allowed_sender,
    delete_block_failed_sender,
    delete_blocked_sender,
    insert_allowed_sender,
)
from dmguard.secrets import FileSecretStore, SECRET_KEYS
from dmguard.setup_logger import SetupLogger
from dmguard.setup_state import (
    SETUP_STAGE_ORDER,
    SetupState,
    StageStatus,
    describe_verbose_stage_changes,
    invalidate_changed_stages,
    load_setup_state,
    save_setup_state,
)


SETUP_STATE_PATH = PROGRAM_DATA_DIR / "setup_state.json"
SETUP_LOG_PATH = PROGRAM_DATA_DIR / "setup.log"
DUCKDNS_ARTIFACT_PATH = PROGRAM_DATA_DIR / "duckdns.txt"
TRAEFIK_DIR = PROGRAM_DATA_DIR / "traefik"
KNOWN_SETUP_OUTPUTS = (
    CONFIG_PATH,
    SECRETS_PATH,
    SETUP_STATE_PATH,
    SETUP_LOG_PATH,
    DUCKDNS_ARTIFACT_PATH,
    TRAEFIK_DIR,
)
CLASSIFIER_FAKE_BASE_CMD = (
    sys.executable,
    "-m",
    "dmguard.classifier_fake",
)
DEFAULT_WARMUP_CLASSIFIER_CMD = (
    *CLASSIFIER_FAKE_BASE_CMD,
    "--force-safe",
)
_SELFTEST_UNSAFE_THRESHOLD = 0.9
SETUP_CONFIG_DEFAULTS = {
    "debug": False,
    "log_level": "INFO",
    "port": 8080,
    "host": "127.0.0.1",
    "debug_dashboard_port": 8081,
}
TEXT_PROMPTS = {
    "public_hostname": "Public DuckDNS hostname",
    "acme_email": "ACME email",
}
SECRET_PROMPTS = {
    "duckdns_token": "DuckDNS token",
    "x_access_token": "X access token",
    "x_refresh_token": "X refresh token",
    "x_consumer_secret": "X consumer secret",
    "x_app_bearer": "X app bearer",
    "hf_token": "Hugging Face token",
}


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="dmguard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup")
    setup_parser.add_argument("--debug", action="store_true")
    setup_parser.add_argument("--log-level", default=SETUP_CONFIG_DEFAULTS["log_level"])
    setup_parser.add_argument("--port", type=int, default=SETUP_CONFIG_DEFAULTS["port"])
    setup_parser.add_argument("--host", default=SETUP_CONFIG_DEFAULTS["host"])
    setup_parser.add_argument(
        "--debug-dashboard-port",
        type=int,
        default=SETUP_CONFIG_DEFAULTS["debug_dashboard_port"],
    )
    setup_parser.add_argument("--public-hostname")
    setup_parser.add_argument("--acme-email")
    setup_parser.add_argument("--duckdns-token")
    setup_parser.add_argument("--x-access-token")
    setup_parser.add_argument("--x-refresh-token")
    setup_parser.add_argument("--x-consumer-secret")
    setup_parser.add_argument("--x-app-bearer")
    setup_parser.add_argument("--hf-token")
    setup_parser.add_argument("--verbose", action="store_true")

    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("--force", action="store_true")

    subparsers.add_parser("warmup")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--full", action="store_true")

    allowlist_parser = subparsers.add_parser("allowlist")
    allowlist_subparsers = allowlist_parser.add_subparsers(
        dest="allowlist_command",
        required=True,
    )
    allowlist_add_parser = allowlist_subparsers.add_parser("add")
    allowlist_add_parser.add_argument("--user-id", required=True)
    allowlist_add_parser.add_argument("--source-event-id", required=True)
    allowlist_remove_parser = allowlist_subparsers.add_parser("remove")
    allowlist_remove_parser.add_argument("--user-id", required=True)

    blockstate_parser = subparsers.add_parser("blockstate")
    blockstate_subparsers = blockstate_parser.add_subparsers(
        dest="blockstate_command",
        required=True,
    )
    blockstate_remove_parser = blockstate_subparsers.add_parser("remove")
    blockstate_remove_parser.add_argument("--user-id", required=True)

    selftest_parser = subparsers.add_parser("selftest")
    selftest_mode_group = selftest_parser.add_mutually_exclusive_group(required=True)
    selftest_mode_group.add_argument("--image", type=Path)
    selftest_mode_group.add_argument("--video", type=Path)
    selftest_force_group = selftest_parser.add_mutually_exclusive_group()
    selftest_force_group.add_argument("--force-safe", action="store_true")
    selftest_force_group.add_argument("--force-unsafe", action="store_true")

    subparsers.add_parser("readycheck")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        if args.command == "setup":
            return handle_setup(args)
        if args.command == "reset":
            return handle_reset(args)
        if args.command == "warmup":
            return handle_warmup()
        if args.command == "status":
            return handle_status(args)
        if args.command == "allowlist":
            return handle_allowlist(args)
        if args.command == "blockstate":
            return handle_blockstate(args)
        if args.command == "selftest":
            return handle_selftest(args)
        if args.command == "readycheck":
            return handle_readycheck()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


def handle_setup(args) -> int:
    logger = SetupLogger(SETUP_LOG_PATH)
    effective_args = {
        "debug": args.debug,
        "log_level": args.log_level,
        "port": args.port,
        "host": args.host,
        "debug_dashboard_port": args.debug_dashboard_port,
        "public_hostname": _get_text_value(args.public_hostname, "public_hostname"),
        "acme_email": _get_text_value(args.acme_email, "acme_email"),
    }
    secret_values = {
        "duckdns_token": _get_secret_value(args.duckdns_token, "duckdns_token"),
        "x_access_token": _get_secret_value(args.x_access_token, "x_access_token"),
        "x_refresh_token": _get_secret_value(args.x_refresh_token, "x_refresh_token"),
        "x_consumer_secret": _get_secret_value(
            args.x_consumer_secret, "x_consumer_secret"
        ),
        "x_app_bearer": _get_secret_value(args.x_app_bearer, "x_app_bearer"),
        "hf_token": _get_secret_value(args.hf_token, "hf_token"),
    }
    state = _load_or_create_setup_state()
    invalidated_stages: list[str] = []
    verbose_messages: list[str] = []

    logger.log("setup started")

    if state.effective_args:
        if args.verbose:
            verbose_messages = describe_verbose_stage_changes(state, effective_args)
        invalidated_stages = invalidate_changed_stages(state, effective_args)
        if args.verbose:
            for message in verbose_messages:
                print(message)
    else:
        state.effective_args = dict(effective_args)

    _write_yaml(CONFIG_PATH, effective_args)
    _write_json(SECRETS_PATH, secret_values)

    timestamp = _utc_now()
    state.last_command = "setup --verbose" if args.verbose else "setup"
    state.updated_at = timestamp
    _mark_stage_done(
        state,
        "preflight",
        timestamp=timestamp,
        artifacts=[str(SETUP_STATE_PATH)],
    )
    _mark_stage_done(
        state,
        "local_config",
        timestamp=timestamp,
        artifacts=[str(CONFIG_PATH)],
    )
    _mark_stage_done(
        state,
        "x_auth",
        timestamp=timestamp,
        artifacts=[str(SECRETS_PATH)],
    )
    save_setup_state(state, SETUP_STATE_PATH)

    logger.log(f"setup saved config_path={CONFIG_PATH}")
    logger.log(f"setup saved secrets_path={SECRETS_PATH}")

    if args.verbose and invalidated_stages:
        print(json.dumps({"invalidated_stages": invalidated_stages}, indent=2))

    return 0


def handle_reset(args) -> int:
    if not args.force:
        print("reset requires --force", file=sys.stderr)
        return 2

    for path in KNOWN_SETUP_OUTPUTS:
        _delete_path(path)

    return 0


def handle_warmup() -> int:
    payload = run_setup_warmup()
    state = load_setup_state(SETUP_STATE_PATH)

    if state is not None:
        timestamp = _utc_now()
        state.last_command = "warmup"
        state.updated_at = timestamp
        _mark_stage_done(state, "warmup", timestamp=timestamp)
        save_setup_state(state, SETUP_STATE_PATH)

    print(json.dumps(payload, indent=2))
    return 0


def handle_status(args) -> int:
    state = load_setup_state(SETUP_STATE_PATH)
    payload = {
        "state_path": str(SETUP_STATE_PATH),
        "configured": state is not None,
        "last_command": state.last_command if state is not None else None,
        "updated_at": state.updated_at if state is not None else None,
        "effective_args": state.effective_args if state is not None else None,
        "stages": _dump_stages(state),
        "remote_checks": None,
    }

    if args.full:
        payload["remote_checks"] = build_remote_checks(state)

    print(json.dumps(payload, indent=2))
    return 0


def handle_allowlist(args) -> int:
    if args.allowlist_command == "add":
        asyncio.run(
            _insert_allowed_sender(
                sender_id=args.user_id,
                source_event_id=args.source_event_id,
            )
        )
        print(f"added allowlist sender {args.user_id}")
        return 0

    if args.allowlist_command == "remove":
        asyncio.run(_delete_allowed_sender(args.user_id))
        print(f"removed allowlist sender {args.user_id}")
        return 0

    raise ValueError(f"Unknown allowlist command: {args.allowlist_command}")


def handle_blockstate(args) -> int:
    asyncio.run(_clear_blockstate(args.user_id))
    print(f"removed local blockstate sender {args.user_id}")
    return 0


def handle_selftest(args) -> int:
    target_path = args.image or args.video
    if not target_path.exists():
        raise ValueError(f"Selftest path does not exist: {target_path}")
    if not target_path.is_file():
        raise ValueError(f"Selftest path is not a file: {target_path}")

    mode = "image" if args.image is not None else "video"
    classifier_cmd = list(CLASSIFIER_FAKE_BASE_CMD)
    if args.force_safe:
        classifier_cmd.append("--force-safe")
    if args.force_unsafe:
        classifier_cmd.append("--force-unsafe")

    response = run_classifier(
        {
            "mode": mode,
            "files": [str(target_path)],
            "policy": "violence_gore",
        },
        classifier_cmd,
    )
    outcome = "unsafe" if response.yes_prob >= _SELFTEST_UNSAFE_THRESHOLD else "safe"

    print(f"result={outcome} file={target_path} yes_prob={response.yes_prob:.2f}")
    if response.trigger_frame_index is not None:
        print(f"trigger_frame_index={response.trigger_frame_index}")
    if response.trigger_time_sec is not None:
        print(f"trigger_time_sec={response.trigger_time_sec}")

    return 0


def handle_readycheck() -> int:
    checks = [
        _build_check_result("db reachable", asyncio.run(_check_db_reachable())),
        _build_check_result("secrets loadable", _check_secrets_loadable()),
        _build_check_result("worker running", _check_app_service_done()),
    ]

    for check in checks:
        if check["ok"]:
            print(f"PASS {check['name']}")
            continue

        print(f"FAIL {check['name']}: {check['error']}")

    return 0 if all(check["ok"] for check in checks) else 1


def run_setup_warmup() -> dict[str, object]:
    response = run_classifier(
        {
            "mode": "image",
            "files": ["warmup.jpg"],
            "policy": "violence_gore",
        },
        DEFAULT_WARMUP_CLASSIFIER_CMD,
    )
    return response.model_dump(mode="json")


def build_remote_checks(state: SetupState | None) -> dict[str, object]:
    if state is None:
        return {
            "duckdns_resolution": {"ok": False, "error": "setup state missing"},
            "public_https": {"ok": False, "error": "setup state missing"},
        }

    hostname = state.effective_args.get("public_hostname")
    if not isinstance(hostname, str) or not hostname:
        return {
            "duckdns_resolution": {"ok": False, "error": "public_hostname missing"},
            "public_https": {"ok": False, "error": "public_hostname missing"},
        }

    return {
        "duckdns_resolution": check_duckdns_resolution(hostname),
        "public_https": check_public_https_reachability(hostname),
    }


def check_duckdns_resolution(hostname: str) -> dict[str, object]:
    try:
        address_info = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        return {"ok": False, "hostname": hostname, "error": str(exc)}

    addresses = sorted({item[4][0] for item in address_info})
    return {"ok": True, "hostname": hostname, "addresses": addresses}


def check_public_https_reachability(hostname: str) -> dict[str, object]:
    url = f"https://{hostname}/webhooks/x"

    try:
        response = httpx.get(url, timeout=5.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        return {"ok": False, "hostname": hostname, "error": str(exc)}

    return {
        "ok": True,
        "hostname": hostname,
        "status_code": response.status_code,
        "url": str(response.request.url),
    }


async def _insert_allowed_sender(*, sender_id: str, source_event_id: str) -> None:
    async with get_connection(DB_PATH) as connection:
        await insert_allowed_sender(
            connection,
            sender_id=sender_id,
            source_event_id=source_event_id,
        )
        await connection.commit()


async def _delete_allowed_sender(sender_id: str) -> None:
    async with get_connection(DB_PATH) as connection:
        await delete_allowed_sender(connection, sender_id)
        await connection.commit()


async def _clear_blockstate(sender_id: str) -> None:
    async with get_connection(DB_PATH) as connection:
        await delete_blocked_sender(connection, sender_id)
        await delete_block_failed_sender(connection, sender_id)
        await connection.commit()


async def _check_db_reachable() -> tuple[bool, str | None]:
    if not DB_PATH.exists():
        return False, "database file missing"

    try:
        async with get_connection(DB_PATH) as connection:
            cursor = await connection.execute("SELECT 1")

            try:
                await cursor.fetchone()
            finally:
                await cursor.close()
    except Exception as exc:
        return False, str(exc)

    return True, None


def _check_secrets_loadable() -> tuple[bool, str | None]:
    store = FileSecretStore(SECRETS_PATH)

    try:
        for key in sorted(SECRET_KEYS):
            store.get(key)
    except Exception as exc:
        return False, str(exc)

    return True, None


def _check_app_service_done() -> tuple[bool, str | None]:
    state = load_setup_state(SETUP_STATE_PATH)
    if state is None:
        return False, "setup state missing"

    app_service = state.stages.get("app_service")
    if app_service is None or app_service.status != "done":
        return False, "app_service stage is not done"

    return True, None


def _build_check_result(
    name: str,
    result: tuple[bool, str | None],
) -> dict[str, object]:
    ok, error = result
    return {"name": name, "ok": ok, "error": error}


def _load_or_create_setup_state() -> SetupState:
    state = load_setup_state(SETUP_STATE_PATH)
    if state is not None:
        return state

    return SetupState(
        last_command="setup",
        effective_args={},
        stages={
            stage_name: StageStatus(
                status="pending",
                started_at=None,
                finished_at=None,
                artifacts=[],
            )
            for stage_name in SETUP_STAGE_ORDER
        },
        updated_at=_utc_now(),
    )


def _mark_stage_done(
    state: SetupState,
    stage_name: str,
    *,
    timestamp: str,
    artifacts: list[str] | None = None,
) -> None:
    state.stages[stage_name] = StageStatus(
        status="done",
        started_at=timestamp,
        finished_at=timestamp,
        artifacts=artifacts or [],
    )


def _get_text_value(current_value: str | None, prompt_key: str) -> str:
    if current_value:
        return current_value

    prompt = f"{TEXT_PROMPTS[prompt_key]}: "
    value = input(prompt).strip()
    if not value:
        raise ValueError(f"{prompt_key} is required")
    return value


def _get_secret_value(current_value: str | None, prompt_key: str) -> str:
    if current_value:
        return current_value

    prompt = f"{SECRET_PROMPTS[prompt_key]}: "
    value = getpass.getpass(prompt).strip()
    if not value:
        raise ValueError(f"{prompt_key} is required")
    return value


def _dump_stages(state: SetupState | None) -> dict[str, object] | None:
    if state is None:
        return None

    return {name: stage.model_dump(mode="json") for name, stage in state.stages.items()}


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _delete_path(path: Path) -> None:
    if not path.exists():
        return

    if path.is_dir():
        shutil.rmtree(path)
        return

    path.unlink()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "KNOWN_SETUP_OUTPUTS",
    "SETUP_LOG_PATH",
    "SETUP_STATE_PATH",
    "build_parser",
    "check_duckdns_resolution",
    "check_public_https_reachability",
    "main",
    "run_setup_warmup",
]
