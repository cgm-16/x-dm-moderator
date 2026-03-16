from pathlib import Path
from typing import Literal
import json
import os
import subprocess
import sys

import pytest
import yaml

from tests.conftest import bootstrap_database, run


def configure_cli_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from dmguard import cli

    data_root = tmp_path / "program-data"
    db_path = data_root / "state.db"
    data_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cli, "PROGRAM_DATA_DIR", data_root)
    monkeypatch.setattr(cli, "CONFIG_PATH", data_root / "config.yaml")
    monkeypatch.setattr(cli, "SECRETS_PATH", data_root / "secrets.bin")
    monkeypatch.setattr(cli, "SETUP_STATE_PATH", data_root / "setup_state.json")
    monkeypatch.setattr(cli, "SETUP_LOG_PATH", data_root / "setup.log")
    monkeypatch.setattr(cli, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(
        cli,
        "KNOWN_SETUP_OUTPUTS",
        (
            cli.CONFIG_PATH,
            cli.SECRETS_PATH,
            cli.SETUP_STATE_PATH,
            cli.SETUP_LOG_PATH,
            data_root / "duckdns.txt",
            data_root / "traefik",
            data_root / "services",
            data_root / "x-webhook.json",
        ),
    )

    return cli


def save_state(
    state_path: Path,
    *,
    stage_statuses: dict[str, str] | None = None,
) -> None:
    from dmguard.setup_state import SetupState, StageStatus, save_setup_state

    stage_statuses = stage_statuses or {}
    done_timestamp = "2026-03-11T12:00:00+00:00"

    def stage_status(stage_name: str, default: str = "pending") -> str:
        return stage_statuses.get(stage_name, default)

    def stage(
        stage_name: str,
        *,
        artifacts: list[str] | None = None,
        default: str = "pending",
    ) -> StageStatus:
        status = stage_status(stage_name, default)
        return StageStatus(
            status=status,
            started_at=done_timestamp if status == "done" else None,
            finished_at=done_timestamp if status == "done" else None,
            artifacts=(artifacts or []) if status == "done" else [],
        )

    save_setup_state(
        SetupState(
            last_command="setup --verbose",
            effective_args={
                "debug": False,
                "log_level": "INFO",
                "classifier_backend": "fake",
                "port": 8080,
                "host": "127.0.0.1",
                "debug_dashboard_port": 8081,
                "public_hostname": "dmguard.duckdns.org",
                "acme_email": "ops@example.com",
            },
            stages={
                "preflight": stage(
                    "preflight", artifacts=[str(state_path)], default="done"
                ),
                "local_config": stage(
                    "local_config",
                    artifacts=[str(state_path.parent / "config.yaml")],
                    default="done",
                ),
                "x_auth": stage(
                    "x_auth",
                    artifacts=[str(state_path.parent / "secrets.bin")],
                    default="done",
                ),
                "duckdns": stage(
                    "duckdns",
                    artifacts=[str(state_path.parent / "duckdns.txt")],
                ),
                "traefik": stage(
                    "traefik",
                    artifacts=[
                        str(state_path.parent / "traefik" / "traefik-static.yml"),
                        str(state_path.parent / "traefik" / "routes.yml"),
                        str(state_path.parent / "traefik" / "acme.json"),
                        str(state_path.parent / "services" / "traefik-service.json"),
                        str(state_path.parent / "services" / "dmguard-service.json"),
                    ],
                ),
                "tls": stage("tls"),
                "public_reachability": stage("public_reachability"),
                "x_webhook": stage(
                    "x_webhook",
                    artifacts=[str(state_path.parent / "x-webhook.json")],
                ),
                "warmup": stage("warmup"),
                "app_service": stage("app_service"),
            },
            updated_at=done_timestamp,
        ),
        state_path,
    )


async def fetch_sender_row(
    db_path: Path,
    table_name: Literal["allowed_senders", "blocked_senders", "block_failed_senders"],
    sender_id: str,
) -> tuple[str, ...] | None:
    from dmguard.db import get_connection

    async with get_connection(db_path) as connection:
        cursor = await connection.execute(
            f"SELECT * FROM {table_name} WHERE sender_id = ?",
            (sender_id,),
        )

        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()


def write_secret_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "duckdns_token": "duckdns-token",
                "x_access_token": "access-token",
                "x_client_id": "client-id",
                "x_consumer_secret": "consumer-secret",
                "x_refresh_token": "refresh-token",
                "x_user_id": "user-id",
                "hf_token": "hf-token",
            }
        ),
        encoding="utf-8",
    )


def write_config_file(path: Path, *, classifier_backend: str = "fake") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "debug": False,
                "log_level": "INFO",
                "classifier_backend": classifier_backend,
                "port": 8080,
                "host": "127.0.0.1",
                "debug_dashboard_port": 8081,
                "public_hostname": "dmguard.duckdns.org",
                "acme_email": "ops@example.com",
            }
        ),
        encoding="utf-8",
    )


def write_operational_artifacts(data_root: Path) -> None:
    (data_root / "duckdns.txt").write_text("dmguard\n", encoding="utf-8")
    (data_root / "traefik").mkdir(parents=True, exist_ok=True)
    (data_root / "traefik" / "traefik-static.yml").write_text(
        "entryPoint=:443\n", encoding="utf-8"
    )
    (data_root / "traefik" / "routes.yml").write_text(
        "http:\n  routers:\n    webhook: {}\n",
        encoding="utf-8",
    )
    (data_root / "traefik" / "acme.json").write_text("{}", encoding="utf-8")
    (data_root / "services").mkdir(parents=True, exist_ok=True)
    (data_root / "services" / "traefik-service.json").write_text(
        '{"name":"XDMModeratorTraefik"}',
        encoding="utf-8",
    )
    (data_root / "services" / "dmguard-service.json").write_text(
        '{"name":"XDMModerator"}',
        encoding="utf-8",
    )
    (data_root / "x-webhook.json").write_text(
        '{"id":"wh-1","url":"https://dmguard.duckdns.org/webhooks/x","valid":true}',
        encoding="utf-8",
    )


async def seed_sender_state(db_path: Path) -> None:
    from dmguard.db import get_connection
    from dmguard.repo_senders import (
        insert_allowed_sender,
        insert_blocked_sender,
        upsert_block_failed_sender,
    )

    async with get_connection(db_path) as connection:
        await insert_allowed_sender(
            connection,
            sender_id="sender-1",
            source_event_id="event-1",
        )
        await insert_blocked_sender(
            connection,
            sender_id="sender-2",
            source_event_id="event-2",
        )
        await upsert_block_failed_sender(
            connection,
            sender_id="sender-2",
            next_retry_at="2026-03-12T00:00:00Z",
        )
        await connection.commit()


def test_build_parser_recognizes_cli_subcommands() -> None:
    from dmguard.cli import build_parser

    parser = build_parser()

    assert parser.parse_args(["setup"]).command == "setup"
    assert (
        parser.parse_args(
            ["setup", "--classifier-backend", "llavaguard"]
        ).classifier_backend
        == "llavaguard"
    )
    assert (
        parser.parse_args(["setup", "--x-client-id", "client-1"]).x_client_id
        == "client-1"
    )
    assert parser.parse_args(["reset", "--force"]).command == "reset"
    assert parser.parse_args(["warmup"]).command == "warmup"
    assert parser.parse_args(["status"]).command == "status"
    assert parser.parse_args(["status", "--full"]).full is True
    allowlist_args = parser.parse_args(
        [
            "allowlist",
            "add",
            "--user-id",
            "sender-1",
            "--source-event-id",
            "event-1",
        ]
    )
    assert allowlist_args.command == "allowlist"
    assert allowlist_args.allowlist_command == "add"
    assert allowlist_args.user_id == "sender-1"
    assert allowlist_args.source_event_id == "event-1"
    blockstate_args = parser.parse_args(
        ["blockstate", "remove", "--user-id", "sender-2"]
    )
    assert blockstate_args.command == "blockstate"
    assert blockstate_args.blockstate_command == "remove"
    assert blockstate_args.user_id == "sender-2"
    selftest_args = parser.parse_args(
        ["selftest", "--video", "clip.mp4", "--force-unsafe"]
    )
    assert selftest_args.command == "selftest"
    assert selftest_args.video == Path("clip.mp4")
    assert selftest_args.force_unsafe is True
    assert parser.parse_args(["readycheck"]).command == "readycheck"


def test_setup_collects_expected_inputs_and_persists_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    text_prompts = iter(["dmguard.duckdns.org", "ops@example.com", "client-id"])
    secret_prompts = iter(
        [
            "duckdns-token",
            "consumer-secret",
            "hf-token",
        ]
    )
    calls: list[tuple[dict[str, object], dict[str, str]]] = []

    monkeypatch.setattr("builtins.input", lambda _: next(text_prompts))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(secret_prompts))
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "_run_preflight_checks", lambda: None)
    monkeypatch.setattr(
        cli,
        "run_pkce_flow",
        lambda client_id: {
            "x_access_token": "access-token",
            "x_refresh_token": "refresh-token",
            "x_user_id": "user-id",
        },
    )
    monkeypatch.setattr(
        cli,
        "execute_setup_flow",
        lambda state, *, state_path, effective_args, secret_values, logger, runtime: (
            calls.append((effective_args, secret_values))
        ),
    )

    exit_code = cli.main(["setup"])

    saved_state = json.loads(cli.SETUP_STATE_PATH.read_text(encoding="utf-8"))
    saved_config = yaml.safe_load(cli.CONFIG_PATH.read_text(encoding="utf-8"))
    saved_secrets = json.loads(cli.SECRETS_PATH.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert calls == [
        (
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
                "x_consumer_secret": "consumer-secret",
                "hf_token": "hf-token",
                "x_client_id": "client-id",
                "x_access_token": "access-token",
                "x_refresh_token": "refresh-token",
                "x_user_id": "user-id",
            },
        )
    ]
    assert saved_state["last_command"] == "setup"
    assert saved_state["effective_args"]["public_hostname"] == "dmguard.duckdns.org"
    assert saved_state["effective_args"]["acme_email"] == "ops@example.com"
    assert saved_state["stages"]["local_config"]["status"] == "done"
    assert saved_state["stages"]["x_auth"]["status"] == "done"
    assert saved_config == {
        "debug": False,
        "log_level": "INFO",
        "classifier_backend": "fake",
        "port": 8080,
        "host": "127.0.0.1",
        "debug_dashboard_port": 8081,
        "public_hostname": "dmguard.duckdns.org",
        "acme_email": "ops@example.com",
    }
    assert saved_secrets == {
        "duckdns_token": "duckdns-token",
        "x_consumer_secret": "consumer-secret",
        "hf_token": "hf-token",
        "x_client_id": "client-id",
        "x_access_token": "access-token",
        "x_refresh_token": "refresh-token",
        "x_user_id": "user-id",
    }


def test_setup_skips_pkce_when_x_auth_already_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)

    # Pre-populate secrets and setup state with x_auth done
    write_secret_file(cli.SECRETS_PATH)
    state_path = cli.SETUP_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_command": "setup",
                "effective_args": {
                    "debug": False,
                    "log_level": "INFO",
                    "classifier_backend": "fake",
                    "port": 8080,
                    "host": "127.0.0.1",
                    "debug_dashboard_port": 8081,
                    "public_hostname": "dmguard.duckdns.org",
                    "acme_email": "ops@example.com",
                },
                "stages": {
                    stage: {
                        "status": "done",
                        "started_at": "2026-03-11T12:00:00Z",
                        "finished_at": "2026-03-11T12:00:01Z",
                        "artifacts": [],
                    }
                    for stage in [
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
                    ]
                },
                "updated_at": "2026-03-11T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    text_prompts = iter(["dmguard.duckdns.org", "ops@example.com", "client-id"])
    secret_prompts = iter(["duckdns-token", "consumer-secret", "hf-token"])
    monkeypatch.setattr("builtins.input", lambda _: next(text_prompts))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(secret_prompts))
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "_run_preflight_checks", lambda: None)
    monkeypatch.setattr(
        cli,
        "run_pkce_flow",
        lambda client_id: (_ for _ in ()).throw(
            AssertionError("PKCE flow should not be called")
        ),
    )
    monkeypatch.setattr(
        cli,
        "execute_setup_flow",
        lambda state, *, state_path, effective_args, secret_values, logger, runtime: (
            None
        ),
    )

    exit_code = cli.main(["setup"])

    assert exit_code == 0
    saved_secrets = json.loads(cli.SECRETS_PATH.read_text(encoding="utf-8"))
    assert saved_secrets["x_access_token"] == "access-token"
    assert saved_secrets["x_refresh_token"] == "refresh-token"
    assert saved_secrets["x_user_id"] == "user-id"


def test_setup_uses_flags_without_prompting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)

    def fail_prompt(_: str) -> str:
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr("builtins.input", fail_prompt)
    monkeypatch.setattr(cli.getpass, "getpass", fail_prompt)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "_run_preflight_checks", lambda: None)
    monkeypatch.setattr(
        cli,
        "run_pkce_flow",
        lambda client_id: {
            "x_access_token": "access-token",
            "x_refresh_token": "refresh-token",
            "x_user_id": "user-id",
        },
    )
    monkeypatch.setattr(
        cli,
        "execute_setup_flow",
        lambda state, *, state_path, effective_args, secret_values, logger, runtime: (
            None
        ),
    )

    exit_code = cli.main(
        [
            "setup",
            "--public-hostname",
            "dmguard.duckdns.org",
            "--acme-email",
            "ops@example.com",
            "--x-client-id",
            "client-id",
            "--duckdns-token",
            "duckdns-token",
            "--x-consumer-secret",
            "consumer-secret",
            "--hf-token",
            "hf-token",
        ]
    )

    saved_secrets = json.loads(cli.SECRETS_PATH.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert saved_secrets["duckdns_token"] == "duckdns-token"


def test_reset_without_force_fails_safely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    cli.SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cli.SETUP_STATE_PATH.write_text("{}", encoding="utf-8")

    exit_code = cli.main(["reset"])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "--force" in captured.err
    assert cli.SETUP_STATE_PATH.exists()


def test_reset_force_deletes_known_setup_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    for path in cli.KNOWN_SETUP_OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix:
            path.write_text("generated", encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)
            (path / "artifact.txt").write_text("generated", encoding="utf-8")

    exit_code = cli.main(["reset", "--force"])

    assert exit_code == 0
    assert all(not path.exists() for path in cli.KNOWN_SETUP_OUTPUTS)


def test_status_prints_local_status_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    cli.SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_state(cli.SETUP_STATE_PATH)

    exit_code = cli.main(["status"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["configured"] is True
    assert payload["last_command"] == "setup --verbose"
    assert payload["remote_checks"] is None
    assert payload["stages"]["local_config"]["status"] == "done"


def test_status_full_adds_remote_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    cli.SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_state(cli.SETUP_STATE_PATH)
    monkeypatch.setattr(
        cli,
        "check_duckdns_resolution",
        lambda hostname: {"ok": True, "hostname": hostname, "addresses": ["1.2.3.4"]},
    )
    monkeypatch.setattr(
        cli,
        "check_public_https_reachability",
        lambda hostname: {"ok": False, "hostname": hostname, "error": "timeout"},
    )

    exit_code = cli.main(["status", "--full"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["remote_checks"] == {
        "duckdns_resolution": {
            "ok": True,
            "hostname": "dmguard.duckdns.org",
            "addresses": ["1.2.3.4"],
        },
        "public_https": {
            "ok": False,
            "hostname": "dmguard.duckdns.org",
            "error": "timeout",
        },
    }


def test_warmup_invokes_setup_warmup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_run_setup_warmup() -> dict[str, object]:
        calls.append("warmup")
        return {
            "policy": "O2_violence_harm_cruelty",
            "rating": "safe",
            "category": "NA: None applying",
            "rationale": "Forced safe for testing",
            "trigger_frame_index": None,
        }

    monkeypatch.setattr(cli, "run_setup_warmup", fake_run_setup_warmup)

    exit_code = cli.main(["warmup"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert calls == ["warmup"]
    assert json.loads(captured.out) == {
        "policy": "O2_violence_harm_cruelty",
        "rating": "safe",
        "category": "NA: None applying",
        "rationale": "Forced safe for testing",
        "trigger_frame_index": None,
    }


def test_run_setup_warmup_uses_configured_llavaguard_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard.classifier_contract import ClassifierResponse

    cli = configure_cli_paths(monkeypatch, tmp_path)
    write_config_file(cli.CONFIG_PATH, classifier_backend="llavaguard")
    calls: list[tuple[dict[str, object], tuple[str, ...]]] = []

    def fake_run_classifier(
        input_data: dict[str, object],
        classifier_cmd: list[str] | tuple[str, ...],
    ) -> ClassifierResponse:
        calls.append((input_data, tuple(classifier_cmd)))
        return ClassifierResponse(
            policy="O2_violence_harm_cruelty",
            rating="safe",
            category="NA: None applying",
            rationale="Warmup ok",
        )

    monkeypatch.setattr(cli, "run_classifier", fake_run_classifier)

    payload = cli.run_setup_warmup()

    assert payload["rating"] == "safe"
    assert calls == [
        (
            {
                "mode": "image",
                "files": ["warmup.jpg"],
                "policy": "O2_violence_harm_cruelty",
            },
            (sys.executable, "-m", "dmguard.classifier_llavaguard"),
        )
    ]


def test_allowlist_add_inserts_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    run(bootstrap_database(cli.DB_PATH))

    exit_code = cli.main(
        [
            "allowlist",
            "add",
            "--user-id",
            "sender-1",
            "--source-event-id",
            "event-1",
        ]
    )

    captured = capsys.readouterr()
    row = run(fetch_sender_row(cli.DB_PATH, "allowed_senders", "sender-1"))

    assert exit_code == 0
    assert captured.err == ""
    assert row is not None
    assert row[0] == "sender-1"
    assert row[2] == "event-1"


def test_allowlist_remove_deletes_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    run(bootstrap_database(cli.DB_PATH))
    run(seed_sender_state(cli.DB_PATH))

    exit_code = cli.main(["allowlist", "remove", "--user-id", "sender-1"])

    captured = capsys.readouterr()
    row = run(fetch_sender_row(cli.DB_PATH, "allowed_senders", "sender-1"))

    assert exit_code == 0
    assert captured.err == ""
    assert row is None


def test_blockstate_remove_clears_local_block_tables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    run(bootstrap_database(cli.DB_PATH))
    run(seed_sender_state(cli.DB_PATH))

    exit_code = cli.main(["blockstate", "remove", "--user-id", "sender-2"])

    captured = capsys.readouterr()
    blocked_row = run(fetch_sender_row(cli.DB_PATH, "blocked_senders", "sender-2"))
    failed_row = run(fetch_sender_row(cli.DB_PATH, "block_failed_senders", "sender-2"))

    assert exit_code == 0
    assert captured.err == ""
    assert blocked_row is None
    assert failed_row is None


def test_selftest_force_safe_prints_human_readable_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    image_path = tmp_path / "image.jpg"
    image_path.write_text("image-bytes", encoding="utf-8")

    exit_code = cli.main(["selftest", "--image", str(image_path), "--force-safe"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert "result=safe" in captured.out
    assert "category=NA: None applying" in captured.out
    assert str(image_path) in captured.out


def test_selftest_force_unsafe_video_prints_trigger_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    video_path = tmp_path / "clip.mp4"
    video_path.write_text("video-bytes", encoding="utf-8")

    exit_code = cli.main(["selftest", "--video", str(video_path), "--force-unsafe"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert "result=unsafe" in captured.out
    assert "category=O2: Violence, Harm, or Cruelty" in captured.out
    assert "trigger_frame_index=0" in captured.out


def test_selftest_missing_file_fails_with_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    missing_path = tmp_path / "missing.jpg"

    exit_code = cli.main(["selftest", "--image", str(missing_path)])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert str(missing_path) in captured.err
    assert "does not exist" in captured.err


def test_selftest_without_force_uses_configured_llavaguard_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from dmguard.classifier_contract import ClassifierResponse

    cli = configure_cli_paths(monkeypatch, tmp_path)
    write_config_file(cli.CONFIG_PATH, classifier_backend="llavaguard")
    image_path = tmp_path / "image.jpg"
    image_path.write_text("image-bytes", encoding="utf-8")
    calls: list[tuple[dict[str, object], tuple[str, ...]]] = []

    def fake_run_classifier(
        input_data: dict[str, object],
        classifier_cmd: list[str] | tuple[str, ...],
    ) -> ClassifierResponse:
        calls.append((input_data, tuple(classifier_cmd)))
        return ClassifierResponse(
            policy="O2_violence_harm_cruelty",
            rating="safe",
            category="NA: None applying",
            rationale="Configured backend",
        )

    monkeypatch.setattr(cli, "run_classifier", fake_run_classifier)

    exit_code = cli.main(["selftest", "--image", str(image_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert "result=safe" in captured.out
    assert calls == [
        (
            {
                "mode": "image",
                "files": [str(image_path)],
                "policy": "O2_violence_harm_cruelty",
            },
            (sys.executable, "-m", "dmguard.classifier_llavaguard"),
        )
    ]


def test_selftest_force_safe_uses_fake_backend_even_with_llavaguard_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from dmguard.classifier_contract import ClassifierResponse

    cli = configure_cli_paths(monkeypatch, tmp_path)
    write_config_file(cli.CONFIG_PATH, classifier_backend="llavaguard")
    image_path = tmp_path / "image.jpg"
    image_path.write_text("image-bytes", encoding="utf-8")
    calls: list[tuple[dict[str, object], tuple[str, ...]]] = []

    def fake_run_classifier(
        input_data: dict[str, object],
        classifier_cmd: list[str] | tuple[str, ...],
    ) -> ClassifierResponse:
        calls.append((input_data, tuple(classifier_cmd)))
        return ClassifierResponse(
            policy="O2_violence_harm_cruelty",
            rating="safe",
            category="NA: None applying",
            rationale="Forced fake backend",
        )

    monkeypatch.setattr(cli, "run_classifier", fake_run_classifier)

    exit_code = cli.main(["selftest", "--image", str(image_path), "--force-safe"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert "result=safe" in captured.out
    assert calls == [
        (
            {
                "mode": "image",
                "files": [str(image_path)],
                "policy": "O2_violence_harm_cruelty",
            },
            (sys.executable, "-m", "dmguard.classifier_fake", "--force-safe"),
        )
    ]


def test_selftest_video_with_llavaguard_backend_classifies_extracted_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from dmguard.classifier_contract import ClassifierResponse
    from dmguard.frame_extractor import FrameInfo

    cli = configure_cli_paths(monkeypatch, tmp_path)
    write_config_file(cli.CONFIG_PATH, classifier_backend="llavaguard")
    video_path = tmp_path / "clip.mp4"
    frame_path = tmp_path / "clip-frame-0.jpg"
    video_path.write_text("video-bytes", encoding="utf-8")
    frame_path.write_text("frame-bytes", encoding="utf-8")
    calls: list[tuple[dict[str, object], tuple[str, ...]]] = []
    cleaned_paths: list[Path] = []

    def fake_extract_frames(video_path_arg: Path, event_id: str) -> list[FrameInfo]:
        assert video_path_arg == video_path
        assert event_id == video_path.stem
        return [FrameInfo(path=frame_path, time_sec=1.0, index=0)]

    def fake_cleanup_media(paths: list[Path]) -> None:
        cleaned_paths.extend(paths)

    def fake_run_classifier(
        input_data: dict[str, object],
        classifier_cmd: list[str] | tuple[str, ...],
    ) -> ClassifierResponse:
        calls.append((input_data, tuple(classifier_cmd)))
        return ClassifierResponse(
            policy="O2_violence_harm_cruelty",
            rating="unsafe",
            category="O2: Violence, Harm, or Cruelty",
            rationale="Unsafe frame",
            trigger_frame_index=0,
        )

    monkeypatch.setattr(cli, "extract_frames", fake_extract_frames)
    monkeypatch.setattr(cli, "cleanup_media", fake_cleanup_media)
    monkeypatch.setattr(cli, "run_classifier", fake_run_classifier)

    exit_code = cli.main(["selftest", "--video", str(video_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert "result=unsafe" in captured.out
    assert "trigger_frame_index=0" in captured.out
    assert calls == [
        (
            {
                "mode": "video",
                "files": [str(frame_path)],
                "policy": "O2_violence_harm_cruelty",
            },
            (sys.executable, "-m", "dmguard.classifier_llavaguard"),
        )
    ]
    assert cleaned_paths == [frame_path]


def test_readycheck_prints_pass_fail_per_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    run(bootstrap_database(cli.DB_PATH))
    write_config_file(cli.CONFIG_PATH)
    write_secret_file(cli.SECRETS_PATH)
    cli.SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_operational_artifacts(cli.SETUP_STATE_PATH.parent)
    save_state(
        cli.SETUP_STATE_PATH,
        stage_statuses={
            "duckdns": "done",
            "traefik": "done",
            "tls": "done",
            "public_reachability": "done",
            "x_webhook": "done",
            "warmup": "done",
            "app_service": "done",
        },
    )
    monkeypatch.setattr(cli, "get_service_status", lambda service_name: "Running")

    exit_code = cli.main(["readycheck"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.strip().splitlines() == [
        "PASS db reachable",
        "PASS secrets loadable",
        "PASS setup stages complete",
        "PASS setup artifacts present",
        "PASS traefik service running",
        "PASS app service running",
    ]


def test_readycheck_returns_non_zero_when_app_service_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    run(bootstrap_database(cli.DB_PATH))
    write_config_file(cli.CONFIG_PATH)
    write_secret_file(cli.SECRETS_PATH)
    cli.SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_operational_artifacts(cli.SETUP_STATE_PATH.parent)
    save_state(
        cli.SETUP_STATE_PATH,
        stage_statuses={
            "duckdns": "done",
            "traefik": "done",
            "tls": "done",
            "public_reachability": "done",
            "x_webhook": "done",
            "warmup": "done",
        },
    )
    monkeypatch.setattr(cli, "get_service_status", lambda service_name: "Running")

    exit_code = cli.main(["readycheck"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == ""
    assert captured.out.strip().splitlines() == [
        "PASS db reachable",
        "PASS secrets loadable",
        "FAIL setup stages complete: app_service stage is not done",
        "PASS setup artifacts present",
        "PASS traefik service running",
        "PASS app service running",
    ]


def test_readycheck_end_to_end_via_subprocess(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = tmp_path / "program-files"
    data_root = tmp_path / "program-data"
    db_path = data_root / "state.db"
    secrets_path = data_root / "secrets.bin"
    state_path = data_root / "setup_state.json"

    app_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    run(bootstrap_database(db_path))
    write_config_file(data_root / "config.yaml")
    write_secret_file(secrets_path)
    write_operational_artifacts(data_root)
    save_state(
        state_path,
        stage_statuses={
            "duckdns": "done",
            "traefik": "done",
            "tls": "done",
            "public_reachability": "done",
            "x_webhook": "done",
            "warmup": "done",
            "app_service": "done",
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from dmguard.cli import main; raise SystemExit(main())",
            "readycheck",
        ],
        capture_output=True,
        check=False,
        cwd=repo_root,
        env={
            **os.environ,
            "DMGUARD_APP_ROOT": str(app_root),
            "DMGUARD_DATA_ROOT": str(data_root),
        },
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip().splitlines() == [
        "PASS db reachable",
        "PASS secrets loadable",
        "PASS setup stages complete",
        "PASS setup artifacts present",
        "PASS traefik service running",
        "PASS app service running",
    ]


def _stub_pkce_flow(client_id):
    return {
        "x_access_token": "access-token",
        "x_refresh_token": "refresh-token",
        "x_user_id": "user-id",
    }


def test_setup_preflight_fails_when_servy_cli_missing_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    app_root = tmp_path / "program-files"
    app_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("builtins.input", lambda _: "dmguard.duckdns.org")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "secret-value")
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "run_pkce_flow", _stub_pkce_flow)
    monkeypatch.setattr(cli, "SERVY_CLI_PATH", tmp_path / "missing" / "servy-cli.exe")
    monkeypatch.setattr(
        cli, "TRAEFIK_BINARY_PATH", app_root / "traefik" / "traefik.exe"
    )
    monkeypatch.setattr(
        cli, "TRAEFIK_TEMPLATES_DIR", app_root / "traefik" / "templates"
    )
    # Create traefik binary and templates so only servy is missing
    (app_root / "traefik").mkdir(parents=True, exist_ok=True)
    (app_root / "traefik" / "traefik.exe").write_text("binary", encoding="utf-8")
    (app_root / "traefik" / "templates").mkdir(parents=True, exist_ok=True)
    (app_root / "traefik" / "templates" / "traefik-static.yml.tpl").write_text(
        "tpl", encoding="utf-8"
    )

    exit_code = cli.main(["setup"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "servy" in captured.err.lower()


def test_setup_preflight_fails_when_traefik_binary_missing_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    app_root = tmp_path / "program-files"
    app_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("builtins.input", lambda _: "dmguard.duckdns.org")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "secret-value")
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "run_pkce_flow", _stub_pkce_flow)
    monkeypatch.setattr(cli, "SERVY_CLI_PATH", app_root / "servy-cli.exe")
    monkeypatch.setattr(
        cli, "TRAEFIK_BINARY_PATH", app_root / "traefik" / "traefik.exe"
    )
    monkeypatch.setattr(
        cli, "TRAEFIK_TEMPLATES_DIR", app_root / "traefik" / "templates"
    )
    # Create servy and templates but not traefik binary
    (app_root / "servy-cli.exe").write_text("binary", encoding="utf-8")
    (app_root / "traefik" / "templates").mkdir(parents=True, exist_ok=True)
    (app_root / "traefik" / "templates" / "traefik-static.yml.tpl").write_text(
        "tpl", encoding="utf-8"
    )

    exit_code = cli.main(["setup"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "traefik" in captured.err.lower()


def test_setup_preflight_fails_when_templates_missing_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    app_root = tmp_path / "program-files"
    app_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("builtins.input", lambda _: "dmguard.duckdns.org")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "secret-value")
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "run_pkce_flow", _stub_pkce_flow)
    monkeypatch.setattr(cli, "SERVY_CLI_PATH", app_root / "servy-cli.exe")
    monkeypatch.setattr(
        cli, "TRAEFIK_BINARY_PATH", app_root / "traefik" / "traefik.exe"
    )
    monkeypatch.setattr(
        cli, "TRAEFIK_TEMPLATES_DIR", app_root / "traefik" / "templates"
    )
    # Create servy and traefik binary but no templates dir
    (app_root / "servy-cli.exe").write_text("binary", encoding="utf-8")
    (app_root / "traefik").mkdir(parents=True, exist_ok=True)
    (app_root / "traefik" / "traefik.exe").write_text("binary", encoding="utf-8")

    exit_code = cli.main(["setup"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "template" in captured.err.lower()


def test_setup_preflight_passes_when_all_prereqs_present_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    app_root = tmp_path / "program-files"

    monkeypatch.setattr("builtins.input", lambda _: "dmguard.duckdns.org")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "secret-value")
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "run_pkce_flow", _stub_pkce_flow)
    monkeypatch.setattr(cli, "SERVY_CLI_PATH", app_root / "servy-cli.exe")
    monkeypatch.setattr(
        cli, "TRAEFIK_BINARY_PATH", app_root / "traefik" / "traefik.exe"
    )
    monkeypatch.setattr(
        cli, "TRAEFIK_TEMPLATES_DIR", app_root / "traefik" / "templates"
    )
    monkeypatch.setattr(
        cli,
        "execute_setup_flow",
        lambda state, *, state_path, effective_args, secret_values, logger, runtime: (
            None
        ),
    )
    # Create all prereqs
    (app_root / "servy-cli.exe").parent.mkdir(parents=True, exist_ok=True)
    (app_root / "servy-cli.exe").write_text("binary", encoding="utf-8")
    (app_root / "traefik" / "templates").mkdir(parents=True, exist_ok=True)
    (app_root / "traefik" / "traefik.exe").write_text("binary", encoding="utf-8")
    (app_root / "traefik" / "templates" / "traefik-static.yml.tpl").write_text(
        "tpl", encoding="utf-8"
    )

    exit_code = cli.main(["setup"])

    assert exit_code == 0
