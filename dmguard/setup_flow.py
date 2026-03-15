from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

import httpx

from dmguard.edge import (
    DMGUARD_SERVICE_NAME,
    TRAEFIK_SERVICE_NAME,
    generate_dmguard_service_def,
    generate_traefik_service_def,
    write_routes_atomically,
)
from dmguard.paths import LOGS_DIR, PROGRAM_DATA_DIR
from dmguard.service_manager import (
    SERVICES_DIR,
    write_service_definition,
)
from dmguard.setup_logger import SetupLogger
from dmguard.setup_state import SetupState, StageStatus, save_setup_state
from dmguard.templates import render_template
from dmguard.x_webhooks import build_public_webhook_url


DUCKDNS_ARTIFACT_PATH = PROGRAM_DATA_DIR / "duckdns.txt"
TRAEFIK_DIR = PROGRAM_DATA_DIR / "traefik"
TRAEFIK_TEMPLATES_DIR = Path(__file__).resolve().parent / "traefik" / "templates"
X_WEBHOOK_ARTIFACT_PATH = PROGRAM_DATA_DIR / "x-webhook.json"
OPERATIONAL_STAGE_NAMES = (
    "duckdns",
    "traefik",
    "tls",
    "public_reachability",
    "app_service",
    "warmup",
    "x_webhook",
)


@dataclass(frozen=True)
class SetupRuntime:
    update_duckdns: Callable[[str, str], None]
    install_service: Callable[[dict[str, object]], None]
    start_service: Callable[[str], None]
    get_service_status: Callable[[str], str]
    check_public_https: Callable[[str], dict[str, object]]
    run_warmup: Callable[[], dict[str, object]]
    ensure_webhook: Callable[[str], dict[str, object]]


def execute_setup_flow(
    state: SetupState,
    *,
    state_path: Path,
    effective_args: dict[str, object],
    secret_values: dict[str, str],
    logger: SetupLogger,
    runtime: SetupRuntime,
) -> None:
    public_hostname = _require_string_arg(effective_args, "public_hostname")
    duckdns_token = _require_secret(secret_values, "duckdns_token")
    https_result: dict[str, object] | None = None

    _run_stage(
        state,
        state_path=state_path,
        stage_name="duckdns",
        logger=logger,
        action=lambda: _run_duckdns_stage(public_hostname, duckdns_token, runtime),
    )
    _run_stage(
        state,
        state_path=state_path,
        stage_name="traefik",
        logger=logger,
        action=lambda: _run_traefik_stage(effective_args, runtime),
    )

    def run_tls_stage() -> Sequence[Path]:
        nonlocal https_result
        https_result = runtime.check_public_https(public_hostname)
        if not https_result.get("ok"):
            raise ValueError(
                f"HTTPS check failed: {https_result.get('error', 'unknown error')}"
            )
        return ()

    _run_stage(
        state,
        state_path=state_path,
        stage_name="tls",
        logger=logger,
        action=run_tls_stage,
    )
    _run_stage(
        state,
        state_path=state_path,
        stage_name="public_reachability",
        logger=logger,
        action=lambda: _run_public_reachability_stage(https_result),
    )
    _run_stage(
        state,
        state_path=state_path,
        stage_name="app_service",
        logger=logger,
        action=lambda: _run_app_service_stage(runtime),
    )
    _run_stage(
        state,
        state_path=state_path,
        stage_name="warmup",
        logger=logger,
        action=lambda: _run_warmup_stage(runtime),
    )
    _run_stage(
        state,
        state_path=state_path,
        stage_name="x_webhook",
        logger=logger,
        action=lambda: _run_x_webhook_stage(public_hostname, runtime),
    )


def skip_operational_stages(
    state: SetupState,
    *,
    state_path: Path,
    logger: SetupLogger,
) -> None:
    finished_at = _utc_now()
    for stage_name in OPERATIONAL_STAGE_NAMES:
        state.stages[stage_name] = StageStatus(
            status="skipped",
            started_at=None,
            finished_at=finished_at,
            artifacts=[],
        )
    state.updated_at = finished_at
    save_setup_state(state, state_path)
    logger.log("setup skipped operational ingress stages on non-Windows platform")


def update_duckdns_record(public_hostname: str, duckdns_token: str) -> None:
    domain = public_hostname.removesuffix(".duckdns.org")
    response = httpx.get(
        "https://www.duckdns.org/update",
        params={"domains": domain, "token": duckdns_token},
        timeout=10.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    if response.text.strip() != "OK":
        raise ValueError(f"DuckDNS update failed: {response.text.strip() or 'empty'}")


def _run_stage(
    state: SetupState,
    *,
    state_path: Path,
    stage_name: str,
    logger: SetupLogger,
    action: Callable[[], Sequence[Path] | None],
) -> None:
    started_at = _utc_now()
    state.stages[stage_name] = StageStatus(
        status="running",
        started_at=started_at,
        finished_at=None,
        artifacts=[],
    )
    state.updated_at = started_at
    save_setup_state(state, state_path)
    logger.log(f"stage {stage_name} started")

    try:
        artifacts = action() or ()
    except Exception as exc:
        finished_at = _utc_now()
        state.stages[stage_name] = StageStatus(
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            artifacts=[],
        )
        state.updated_at = finished_at
        save_setup_state(state, state_path)
        logger.log(f"stage {stage_name} failed error={exc}")
        raise

    finished_at = _utc_now()
    state.stages[stage_name] = StageStatus(
        status="done",
        started_at=started_at,
        finished_at=finished_at,
        artifacts=[str(path) for path in artifacts],
    )
    state.updated_at = finished_at
    save_setup_state(state, state_path)
    logger.log(f"stage {stage_name} done artifacts={len(tuple(artifacts))}")


def _run_duckdns_stage(
    public_hostname: str,
    duckdns_token: str,
    runtime: SetupRuntime,
) -> Sequence[Path]:
    runtime.update_duckdns(public_hostname, duckdns_token)
    DUCKDNS_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DUCKDNS_ARTIFACT_PATH.write_text(f"{public_hostname}\n", encoding="utf-8")
    return (DUCKDNS_ARTIFACT_PATH,)


def _run_traefik_stage(
    effective_args: dict[str, object],
    runtime: SetupRuntime,
) -> Sequence[Path]:
    rendered_static, rendered_routes = _render_traefik_files(effective_args)
    traefik_static_path = _traefik_static_path()
    routes_path = _routes_path()
    acme_storage_path = _acme_storage_path()
    traefik_service_def_path = _traefik_service_def_path()
    dmguard_service_def_path = _dmguard_service_def_path()

    TRAEFIK_DIR.mkdir(parents=True, exist_ok=True)
    traefik_static_path.write_text(rendered_static, encoding="utf-8")
    write_routes_atomically(rendered_routes, routes_path)
    acme_storage_path.write_text("{}", encoding="utf-8")

    traefik_service_def = generate_traefik_service_def()
    dmguard_service_def = generate_dmguard_service_def()
    write_service_definition(traefik_service_def_path, traefik_service_def)
    write_service_definition(dmguard_service_def_path, dmguard_service_def)

    runtime.install_service(traefik_service_def)
    runtime.start_service(TRAEFIK_SERVICE_NAME)

    traefik_status = runtime.get_service_status(TRAEFIK_SERVICE_NAME)
    if traefik_status != "Running":
        raise ValueError(f"{TRAEFIK_SERVICE_NAME} service status is not Running")

    return (
        traefik_static_path,
        routes_path,
        acme_storage_path,
        traefik_service_def_path,
        dmguard_service_def_path,
    )


def _render_traefik_files(effective_args: dict[str, object]) -> tuple[str, str]:
    public_hostname = _require_string_arg(effective_args, "public_hostname")
    acme_email = _require_string_arg(effective_args, "acme_email")
    debug_dashboard_port = str(effective_args["debug_dashboard_port"])
    template_vars = {
        "PUBLIC_HOSTNAME": public_hostname,
        "BACKEND_URL": "http://127.0.0.1:8080",
        "DEBUG_DASHBOARD_PORT": debug_dashboard_port,
        "ACME_EMAIL": acme_email,
        "ACME_STORAGE_PATH": str(_acme_storage_path()),
        "TRAEFIK_LOG_PATH": str(LOGS_DIR / "traefik.log"),
        "TRAEFIK_ROUTES_PATH": str(_routes_path()),
    }

    rendered_static = render_template(_traefik_static_template_path(), template_vars)
    if effective_args.get("debug") is True:
        rendered_routes = render_template(_routes_debug_template_path(), template_vars)
    else:
        rendered_routes = render_template(_routes_normal_template_path(), template_vars)

    return rendered_static, rendered_routes


def _run_app_service_stage(runtime: SetupRuntime) -> Sequence[Path]:
    dmguard_service_def = generate_dmguard_service_def()
    runtime.install_service(dmguard_service_def)
    runtime.start_service(DMGUARD_SERVICE_NAME)

    dmguard_status = runtime.get_service_status(DMGUARD_SERVICE_NAME)
    if dmguard_status != "Running":
        raise ValueError(f"{DMGUARD_SERVICE_NAME} service status is not Running")

    return ()


def _run_public_reachability_stage(
    https_result: dict[str, object] | None,
) -> Sequence[Path]:
    if https_result is None:
        raise ValueError("TLS check result missing")

    # 400 is expected when the webhook endpoint receives a bare GET without
    # a valid X CRC payload — it proves the route is publicly reachable and
    # TLS terminates correctly even though the app rejects the request body.
    status_code = https_result.get("status_code")
    if status_code not in {200, 400}:
        raise ValueError(f"Unexpected public HTTPS status code: {status_code}")
    return ()


def _run_warmup_stage(runtime: SetupRuntime) -> Sequence[Path]:
    runtime.run_warmup()
    return ()


def _run_x_webhook_stage(
    public_hostname: str,
    runtime: SetupRuntime,
) -> Sequence[Path]:
    webhook = runtime.ensure_webhook(build_public_webhook_url(public_hostname))
    X_WEBHOOK_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    X_WEBHOOK_ARTIFACT_PATH.write_text(
        json.dumps(webhook, indent=2),
        encoding="utf-8",
    )
    return (X_WEBHOOK_ARTIFACT_PATH,)


def _require_secret(secret_values: dict[str, str], key: str) -> str:
    value = secret_values.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing setup secret: {key}")
    return value


def _require_string_arg(effective_args: dict[str, object], key: str) -> str:
    value = effective_args.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing setup argument: {key}")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _traefik_static_template_path() -> Path:
    return TRAEFIK_TEMPLATES_DIR / "traefik-static.yml.tpl"


def _routes_normal_template_path() -> Path:
    return TRAEFIK_TEMPLATES_DIR / "routes-normal.yml.tpl"


def _routes_debug_template_path() -> Path:
    return TRAEFIK_TEMPLATES_DIR / "routes-debug.yml.tpl"


def _traefik_static_path() -> Path:
    return TRAEFIK_DIR / "traefik-static.yml"


def _routes_path() -> Path:
    return TRAEFIK_DIR / "routes.yml"


def _acme_storage_path() -> Path:
    return TRAEFIK_DIR / "acme.json"


def _traefik_service_def_path() -> Path:
    return SERVICES_DIR / "traefik-service.json"


def _dmguard_service_def_path() -> Path:
    return SERVICES_DIR / "dmguard-service.json"


__all__ = [
    "DUCKDNS_ARTIFACT_PATH",
    "OPERATIONAL_STAGE_NAMES",
    "SERVICES_DIR",
    "SetupRuntime",
    "TRAEFIK_DIR",
    "TRAEFIK_TEMPLATES_DIR",
    "X_WEBHOOK_ARTIFACT_PATH",
    "execute_setup_flow",
    "skip_operational_stages",
    "update_duckdns_record",
]
