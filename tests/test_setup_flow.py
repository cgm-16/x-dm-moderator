import json
from pathlib import Path

import pytest
import yaml

from dmguard.setup_logger import SetupLogger
from dmguard.setup_state import SETUP_STAGE_ORDER, SetupState, StageStatus


def make_state() -> SetupState:
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
        updated_at="2026-03-15T00:00:00+00:00",
    )


def setup_inputs() -> tuple[dict[str, object], dict[str, str]]:
    return (
        {
            "debug": False,
            "log_level": "INFO",
            "classifier_backend": "fake",
            "port": 8080,
            "host": "127.0.0.1",
            "debug_dashboard_port": 8081,
            "public_hostname": "dmguard.duckdns.org",
            "acme_email": "ops@example.com",
        },
        {
            "duckdns_token": "duckdns-token",
            "x_access_token": "access-token",
            "x_consumer_secret": "consumer-secret",
            "x_user_id": "bot-user-id",
            "hf_token": "hf-token",
        },
    )


def write_templates(template_dir: Path) -> None:
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "traefik-static.yml.tpl").write_text(
        "entryPoint: ':443'\nemail: '{{ACME_EMAIL}}'\nstorage: '{{ACME_STORAGE_PATH}}'\ndata_dir: '{{TRAEFIK_DATA_DIR}}'\n",
        encoding="utf-8",
    )
    (template_dir / "routes-normal.yml.tpl").write_text(
        "http:\n  routers:\n    webhook:\n      rule: Host(`{{PUBLIC_HOSTNAME}}`) && Path(`/webhooks/x`)\n",
        encoding="utf-8",
    )
    (template_dir / "routes-debug.yml.tpl").write_text(
        "http:\n  routers:\n    webhook:\n      rule: Host(`{{PUBLIC_HOSTNAME}}`) && Path(`/webhooks/x`)\n    dashboard:\n      rule: PathPrefix(`/`)\n",
        encoding="utf-8",
    )


def test_execute_setup_flow_marks_operational_stages_done_and_writes_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dmguard.setup_flow as setup_flow

    state_path = tmp_path / "setup_state.json"
    logger = SetupLogger(tmp_path / "setup.log")
    state = make_state()
    effective_args, secret_values = setup_inputs()
    template_dir = tmp_path / "templates"
    write_templates(template_dir)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(setup_flow, "DUCKDNS_ARTIFACT_PATH", tmp_path / "duckdns.txt")
    monkeypatch.setattr(setup_flow, "TRAEFIK_DIR", tmp_path / "traefik")
    monkeypatch.setattr(setup_flow, "TRAEFIK_TEMPLATES_DIR", template_dir)
    monkeypatch.setattr(setup_flow, "SERVICES_DIR", tmp_path / "services")
    monkeypatch.setattr(
        setup_flow, "X_WEBHOOK_ARTIFACT_PATH", tmp_path / "x-webhook.json"
    )
    monkeypatch.setattr(
        setup_flow,
        "SetupRuntime",
        setup_flow.SetupRuntime,
    )

    runtime = setup_flow.SetupRuntime(
        update_duckdns=lambda hostname, token: calls.append(("duckdns", hostname)),
        install_service=lambda service_def: calls.append(
            ("install", service_def["name"])
        ),
        start_service=lambda service_name: calls.append(("start", service_name)),
        get_service_status=lambda service_name: "Running",
        check_public_https=lambda hostname: {
            "ok": True,
            "hostname": hostname,
            "status_code": 400,
            "url": f"https://{hostname}/webhooks/x",
        },
        run_warmup=lambda: {
            "rating": "safe",
            "category": "NA: None applying",
        },
        ensure_webhook=lambda webhook_url: {
            "id": "wh-1",
            "url": webhook_url,
            "valid": True,
        },
    )

    setup_flow.execute_setup_flow(
        state,
        state_path=state_path,
        effective_args=effective_args,
        secret_values=secret_values,
        logger=logger,
        runtime=runtime,
    )

    assert state.stages["duckdns"].status == "done"
    assert state.stages["traefik"].status == "done"
    assert state.stages["tls"].status == "done"
    assert state.stages["public_reachability"].status == "done"
    assert state.stages["warmup"].status == "done"
    assert state.stages["x_webhook"].status == "done"
    assert state.stages["app_service"].status == "done"
    assert calls == [
        ("duckdns", "dmguard.duckdns.org"),
        ("install", "XDMModeratorTraefik"),
        ("start", "XDMModeratorTraefik"),
        ("install", "XDMModerator"),
        ("start", "XDMModerator"),
    ]
    assert (tmp_path / "duckdns.txt").exists()
    assert (tmp_path / "traefik" / "traefik-static.yml").exists()
    assert (tmp_path / "traefik" / "routes.yml").exists()
    assert (tmp_path / "traefik" / "acme.json").exists()
    assert (tmp_path / "services" / "traefik-service.json").exists()
    assert (tmp_path / "services" / "dmguard-service.json").exists()
    assert json.loads((tmp_path / "x-webhook.json").read_text(encoding="utf-8")) == {
        "id": "wh-1",
        "url": "https://dmguard.duckdns.org/webhooks/x",
        "valid": True,
    }


def test_execute_setup_flow_marks_failed_stage_and_stops_after_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dmguard.setup_flow as setup_flow

    state_path = tmp_path / "setup_state.json"
    logger = SetupLogger(tmp_path / "setup.log")
    state = make_state()
    effective_args, secret_values = setup_inputs()
    template_dir = tmp_path / "templates"
    write_templates(template_dir)

    monkeypatch.setattr(setup_flow, "DUCKDNS_ARTIFACT_PATH", tmp_path / "duckdns.txt")
    monkeypatch.setattr(setup_flow, "TRAEFIK_DIR", tmp_path / "traefik")
    monkeypatch.setattr(setup_flow, "TRAEFIK_TEMPLATES_DIR", template_dir)
    monkeypatch.setattr(setup_flow, "SERVICES_DIR", tmp_path / "services")
    monkeypatch.setattr(
        setup_flow, "X_WEBHOOK_ARTIFACT_PATH", tmp_path / "x-webhook.json"
    )

    runtime = setup_flow.SetupRuntime(
        update_duckdns=lambda hostname, token: (_ for _ in ()).throw(ValueError("KO")),
        install_service=lambda service_def: None,
        start_service=lambda service_name: None,
        get_service_status=lambda service_name: "Running",
        check_public_https=lambda hostname: {"ok": True, "hostname": hostname},
        run_warmup=lambda: {"rating": "safe"},
        ensure_webhook=lambda webhook_url: {
            "id": "wh-1",
            "url": webhook_url,
            "valid": True,
        },
    )

    with pytest.raises(ValueError, match="KO"):
        setup_flow.execute_setup_flow(
            state,
            state_path=state_path,
            effective_args=effective_args,
            secret_values=secret_values,
            logger=logger,
            runtime=runtime,
        )

    assert state.stages["duckdns"].status == "failed"
    assert state.stages["traefik"].status == "pending"
    saved_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved_state["stages"]["duckdns"]["status"] == "failed"


def test_execute_setup_flow_fails_when_service_does_not_reach_running_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dmguard.setup_flow as setup_flow

    state_path = tmp_path / "setup_state.json"
    logger = SetupLogger(tmp_path / "setup.log")
    state = make_state()
    effective_args, secret_values = setup_inputs()
    template_dir = tmp_path / "templates"
    write_templates(template_dir)

    monkeypatch.setattr(setup_flow, "DUCKDNS_ARTIFACT_PATH", tmp_path / "duckdns.txt")
    monkeypatch.setattr(setup_flow, "TRAEFIK_DIR", tmp_path / "traefik")
    monkeypatch.setattr(setup_flow, "TRAEFIK_TEMPLATES_DIR", template_dir)
    monkeypatch.setattr(setup_flow, "SERVICES_DIR", tmp_path / "services")
    monkeypatch.setattr(
        setup_flow, "X_WEBHOOK_ARTIFACT_PATH", tmp_path / "x-webhook.json"
    )

    runtime = setup_flow.SetupRuntime(
        update_duckdns=lambda hostname, token: None,
        install_service=lambda service_def: None,
        start_service=lambda service_name: None,
        get_service_status=lambda service_name: (
            "Stopped" if service_name == "XDMModerator" else "Running"
        ),
        check_public_https=lambda hostname: {
            "ok": True,
            "hostname": hostname,
            "status_code": 400,
            "url": f"https://{hostname}/webhooks/x",
        },
        run_warmup=lambda: {"rating": "safe"},
        ensure_webhook=lambda webhook_url: {
            "id": "wh-1",
            "url": webhook_url,
            "valid": True,
        },
    )

    with pytest.raises(ValueError, match="Running"):
        setup_flow.execute_setup_flow(
            state,
            state_path=state_path,
            effective_args=effective_args,
            secret_values=secret_values,
            logger=logger,
            runtime=runtime,
        )

    assert state.stages["app_service"].status == "failed"


def test_render_traefik_files_debug_produces_valid_yaml_with_both_routers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dmguard.setup_flow as setup_flow

    template_dir = tmp_path / "templates"
    write_templates(template_dir)
    monkeypatch.setattr(setup_flow, "TRAEFIK_DIR", tmp_path / "traefik")
    monkeypatch.setattr(setup_flow, "TRAEFIK_TEMPLATES_DIR", template_dir)

    effective_args = {
        "debug": True,
        "debug_dashboard_port": 8081,
        "public_hostname": "dmguard.duckdns.org",
        "acme_email": "ops@example.com",
    }
    _, rendered_routes = setup_flow._render_traefik_files(effective_args)
    parsed = yaml.safe_load(rendered_routes)

    assert isinstance(parsed, dict)
    routers = parsed["http"]["routers"]
    assert "webhook" in routers, "debug routes must include the webhook router"
    assert "dashboard" in routers, "debug routes must include the dashboard router"


def test_render_traefik_files_normal_has_webhook_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dmguard.setup_flow as setup_flow

    template_dir = tmp_path / "templates"
    write_templates(template_dir)
    monkeypatch.setattr(setup_flow, "TRAEFIK_DIR", tmp_path / "traefik")
    monkeypatch.setattr(setup_flow, "TRAEFIK_TEMPLATES_DIR", template_dir)

    effective_args = {
        "debug": False,
        "debug_dashboard_port": 8081,
        "public_hostname": "dmguard.duckdns.org",
        "acme_email": "ops@example.com",
    }
    _, rendered_routes = setup_flow._render_traefik_files(effective_args)
    parsed = yaml.safe_load(rendered_routes)

    assert isinstance(parsed, dict)
    routers = parsed["http"]["routers"]
    assert "webhook" in routers
    assert "dashboard" not in routers
