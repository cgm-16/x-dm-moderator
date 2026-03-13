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
        ),
    )

    return cli


def save_state(state_path: Path, *, app_service_status: str = "pending") -> None:
    from dmguard.setup_state import SetupState, StageStatus, save_setup_state

    save_setup_state(
        SetupState(
            last_command="setup --verbose",
            effective_args={
                "debug": False,
                "log_level": "INFO",
                "port": 8080,
                "host": "127.0.0.1",
                "debug_dashboard_port": 8081,
                "public_hostname": "dmguard.duckdns.org",
                "acme_email": "ops@example.com",
            },
            stages={
                "preflight": StageStatus(
                    status="done",
                    started_at="2026-03-11T12:00:00+00:00",
                    finished_at="2026-03-11T12:00:00+00:00",
                    artifacts=[str(state_path)],
                ),
                "local_config": StageStatus(
                    status="done",
                    started_at="2026-03-11T12:00:00+00:00",
                    finished_at="2026-03-11T12:00:00+00:00",
                    artifacts=[str(state_path.parent / "config.yaml")],
                ),
                "x_auth": StageStatus(
                    status="done",
                    started_at="2026-03-11T12:00:00+00:00",
                    finished_at="2026-03-11T12:00:00+00:00",
                    artifacts=[str(state_path.parent / "secrets.bin")],
                ),
                "duckdns": StageStatus(
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    artifacts=[],
                ),
                "traefik": StageStatus(
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    artifacts=[],
                ),
                "tls": StageStatus(
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    artifacts=[],
                ),
                "public_reachability": StageStatus(
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    artifacts=[],
                ),
                "x_webhook": StageStatus(
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    artifacts=[],
                ),
                "warmup": StageStatus(
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    artifacts=[],
                ),
                "app_service": StageStatus(
                    status=app_service_status,
                    started_at=(
                        "2026-03-11T12:00:00+00:00"
                        if app_service_status == "done"
                        else None
                    ),
                    finished_at=(
                        "2026-03-11T12:00:00+00:00"
                        if app_service_status == "done"
                        else None
                    ),
                    artifacts=[],
                ),
            },
            updated_at="2026-03-11T12:00:00+00:00",
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
                "x_refresh_token": "refresh-token",
                "x_consumer_secret": "consumer-secret",
                "x_app_bearer": "app-bearer",
                "hf_token": "hf-token",
            }
        ),
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
    text_prompts = iter(["dmguard.duckdns.org", "ops@example.com"])
    secret_prompts = iter(
        [
            "duckdns-token",
            "access-token",
            "refresh-token",
            "consumer-secret",
            "app-bearer",
            "hf-token",
        ]
    )

    monkeypatch.setattr("builtins.input", lambda _: next(text_prompts))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(secret_prompts))

    exit_code = cli.main(["setup"])

    saved_state = json.loads(cli.SETUP_STATE_PATH.read_text(encoding="utf-8"))
    saved_config = yaml.safe_load(cli.CONFIG_PATH.read_text(encoding="utf-8"))
    saved_secrets = json.loads(cli.SECRETS_PATH.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert saved_state["last_command"] == "setup"
    assert saved_state["effective_args"]["public_hostname"] == "dmguard.duckdns.org"
    assert saved_state["effective_args"]["acme_email"] == "ops@example.com"
    assert saved_state["stages"]["local_config"]["status"] == "done"
    assert saved_state["stages"]["x_auth"]["status"] == "done"
    assert saved_config == {
        "debug": False,
        "log_level": "INFO",
        "port": 8080,
        "host": "127.0.0.1",
        "debug_dashboard_port": 8081,
        "public_hostname": "dmguard.duckdns.org",
        "acme_email": "ops@example.com",
    }
    assert saved_secrets == {
        "duckdns_token": "duckdns-token",
        "x_access_token": "access-token",
        "x_refresh_token": "refresh-token",
        "x_consumer_secret": "consumer-secret",
        "x_app_bearer": "app-bearer",
        "hf_token": "hf-token",
    }


def test_setup_uses_flags_without_prompting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)

    def fail_prompt(_: str) -> str:
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr("builtins.input", fail_prompt)
    monkeypatch.setattr(cli.getpass, "getpass", fail_prompt)

    exit_code = cli.main(
        [
            "setup",
            "--public-hostname",
            "dmguard.duckdns.org",
            "--acme-email",
            "ops@example.com",
            "--duckdns-token",
            "duckdns-token",
            "--x-access-token",
            "access-token",
            "--x-refresh-token",
            "refresh-token",
            "--x-consumer-secret",
            "consumer-secret",
            "--x-app-bearer",
            "app-bearer",
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


def test_readycheck_prints_pass_fail_per_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    run(bootstrap_database(cli.DB_PATH))
    write_secret_file(cli.SECRETS_PATH)
    cli.SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_state(cli.SETUP_STATE_PATH, app_service_status="done")

    exit_code = cli.main(["readycheck"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.strip().splitlines() == [
        "PASS db reachable",
        "PASS secrets loadable",
        "PASS worker running",
    ]


def test_readycheck_returns_non_zero_when_app_service_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    cli = configure_cli_paths(monkeypatch, tmp_path)
    run(bootstrap_database(cli.DB_PATH))
    write_secret_file(cli.SECRETS_PATH)
    cli.SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_state(cli.SETUP_STATE_PATH)

    exit_code = cli.main(["readycheck"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.err == ""
    assert captured.out.strip().splitlines() == [
        "PASS db reachable",
        "PASS secrets loadable",
        "FAIL worker running: app_service stage is not done",
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
    write_secret_file(secrets_path)
    save_state(state_path, app_service_status="done")

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
        "PASS worker running",
    ]
