import subprocess

import pytest


def test_install_service_builds_expected_servy_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard.edge import generate_dmguard_service_def
    from dmguard import service_manager

    recorded: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        recorded.append(command)
        assert check is True
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(service_manager.sys, "platform", "win32")
    monkeypatch.setattr(service_manager.subprocess, "run", fake_run)

    service_manager.install_service(generate_dmguard_service_def())

    assert recorded == [
        [
            "C:/Program Files/Servy/servy-cli.exe",
            "install",
            "--quiet",
            "--name",
            "XDMModerator",
            "--displayName",
            "XDMModerator",
            "--description",
            "XDMModerator application service",
            "--path",
            "C:/Program Files/XDMModerator/dmguard.exe",
            "--startupDir",
            "C:/Program Files/XDMModerator",
            "--startupType",
            "Automatic",
            "--stdout",
            "C:/ProgramData/XDMModerator/logs/dmguard-service.out.log",
            "--stderr",
            "C:/ProgramData/XDMModerator/logs/dmguard-service.err.log",
            "--deps=XDMModeratorTraefik",
        ]
    ]


def test_start_service_builds_expected_servy_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard import service_manager

    recorded: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        recorded.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(service_manager.sys, "platform", "win32")
    monkeypatch.setattr(service_manager.subprocess, "run", fake_run)

    service_manager.start_service("XDMModeratorTraefik")

    assert recorded == [
        [
            "C:/Program Files/Servy/servy-cli.exe",
            "start",
            "--quiet",
            "--name",
            "XDMModeratorTraefik",
        ]
    ]


def test_get_service_status_returns_running_on_non_windows() -> None:
    from dmguard import service_manager

    assert service_manager.get_service_status("XDMModerator") == "Running"
