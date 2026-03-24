import subprocess

import pytest


def test_install_service_builds_expected_servy_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dmguard import edge
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

    definition = edge.generate_dmguard_service_def()
    service_manager.install_service(definition)

    assert recorded == [
        [
            "C:/Program Files/Servy/servy-cli.exe",
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
            f"--params={definition['params']}",
            f"--deps={'; '.join(str(dep) for dep in definition['deps'])}",
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
