from pathlib import Path
import json

import pytest
import yaml


def configure_cli_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from dmguard import cli

    data_root = tmp_path / "program-data"

    monkeypatch.setattr(cli, "PROGRAM_DATA_DIR", data_root)
    monkeypatch.setattr(cli, "CONFIG_PATH", data_root / "config.yaml")
    monkeypatch.setattr(cli, "SECRETS_PATH", data_root / "secrets.bin")
    monkeypatch.setattr(cli, "SETUP_STATE_PATH", data_root / "setup_state.json")
    monkeypatch.setattr(cli, "SETUP_LOG_PATH", data_root / "setup.log")
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


def save_state(state_path: Path) -> None:
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
                    status="pending",
                    started_at=None,
                    finished_at=None,
                    artifacts=[],
                ),
            },
            updated_at="2026-03-11T12:00:00+00:00",
        ),
        state_path,
    )


def test_build_parser_recognizes_setup_subcommands() -> None:
    from dmguard.cli import build_parser

    parser = build_parser()

    assert parser.parse_args(["setup"]).command == "setup"
    assert parser.parse_args(["reset", "--force"]).command == "reset"
    assert (
        parser.parse_args(["selftest", "--image", "sample.jpg"]).command == "selftest"
    )
    assert parser.parse_args(["warmup"]).command == "warmup"
    assert parser.parse_args(["status"]).command == "status"
    assert parser.parse_args(["status", "--full"]).full is True


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
        return {"policy": "violence_gore", "yes_prob": 0.01}

    monkeypatch.setattr(cli, "run_setup_warmup", fake_run_setup_warmup)

    exit_code = cli.main(["warmup"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert calls == ["warmup"]
    assert json.loads(captured.out) == {
        "policy": "violence_gore",
        "yes_prob": 0.01,
    }


def test_selftest_force_safe_prints_safe_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from dmguard import cli
    from dmguard.classifier_contract import ClassifierResponse

    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"image")
    calls: list[tuple[dict[str, object], tuple[str, ...]]] = []

    def fake_run_classifier(
        input_data: dict[str, object], classifier_cmd: tuple[str, ...]
    ) -> ClassifierResponse:
        calls.append((input_data, classifier_cmd))
        return ClassifierResponse(policy="violence_gore", yes_prob=0.01)

    monkeypatch.setattr(cli, "run_classifier", fake_run_classifier)

    exit_code = cli.main(["selftest", "--image", str(image_path), "--force-safe"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "safe" in captured.out.lower()
    assert "0.01" in captured.out
    assert calls == [
        (
            {
                "mode": "image",
                "files": [str(image_path)],
                "policy": "violence_gore",
            },
            (
                cli.DEFAULT_SELFTEST_CLASSIFIER_MODULE[0],
                cli.DEFAULT_SELFTEST_CLASSIFIER_MODULE[1],
                cli.DEFAULT_SELFTEST_CLASSIFIER_MODULE[2],
                "--force-safe",
            ),
        )
    ]


def test_selftest_force_unsafe_video_prints_trigger_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from dmguard import cli
    from dmguard.classifier_contract import ClassifierResponse

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")

    def fake_run_classifier(
        input_data: dict[str, object], classifier_cmd: tuple[str, ...]
    ) -> ClassifierResponse:
        assert input_data == {
            "mode": "video",
            "files": [str(video_path)],
            "policy": "violence_gore",
        }
        assert classifier_cmd == (
            cli.DEFAULT_SELFTEST_CLASSIFIER_MODULE[0],
            cli.DEFAULT_SELFTEST_CLASSIFIER_MODULE[1],
            cli.DEFAULT_SELFTEST_CLASSIFIER_MODULE[2],
            "--force-unsafe",
        )
        return ClassifierResponse(
            policy="violence_gore",
            yes_prob=0.99,
            trigger_frame_index=0,
            trigger_time_sec=1.0,
        )

    monkeypatch.setattr(cli, "run_classifier", fake_run_classifier)

    exit_code = cli.main(["selftest", "--video", str(video_path), "--force-unsafe"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "unsafe" in captured.out.lower()
    assert "trigger" in captured.out.lower()
    assert "0" in captured.out
    assert "1.0" in captured.out


def test_selftest_invalid_path_fails_with_clear_error_message(
    tmp_path: Path, capsys
) -> None:
    from dmguard import cli

    missing_path = tmp_path / "missing.jpg"

    exit_code = cli.main(["selftest", "--image", str(missing_path)])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not found" in captured.err.lower()
    assert str(missing_path) in captured.err
