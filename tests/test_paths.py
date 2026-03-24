import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_resolve_paths_windows_defaults():
    from dmguard.paths import resolve_paths

    paths = resolve_paths(platform="win32", env={})

    assert paths.program_files_dir == Path("C:/Program Files/XDMModerator")
    assert paths.program_data_dir == Path("C:/ProgramData/XDMModerator")
    assert paths.db_path == Path("C:/ProgramData/XDMModerator/state.db")
    assert paths.config_path == Path("C:/ProgramData/XDMModerator/config.yaml")
    assert paths.secrets_path == Path("C:/ProgramData/XDMModerator/secrets.bin")
    assert paths.logs_dir == Path("C:/ProgramData/XDMModerator/logs")
    assert paths.tmp_dir == Path("C:/ProgramData/XDMModerator/tmp")


def test_resolve_paths_non_windows_env_override():
    from dmguard.paths import resolve_paths

    paths = resolve_paths(
        platform="darwin",
        env={
            "DMGUARD_APP_ROOT": "/tmp/dmguard-app",
            "DMGUARD_DATA_ROOT": "/tmp/dmguard-data",
        },
    )

    assert paths.program_files_dir == Path("/tmp/dmguard-app")
    assert paths.program_data_dir == Path("/tmp/dmguard-data")
    assert paths.db_path == Path("/tmp/dmguard-data/state.db")
    assert paths.config_path == Path("/tmp/dmguard-data/config.yaml")
    assert paths.secrets_path == Path("/tmp/dmguard-data/secrets.bin")
    assert paths.logs_dir == Path("/tmp/dmguard-data/logs")
    assert paths.tmp_dir == Path("/tmp/dmguard-data/tmp")


def test_resolve_paths_non_windows_requires_both_env_vars():
    from dmguard.paths import resolve_paths

    with pytest.raises(ValueError) as exc_info:
        resolve_paths(platform="darwin", env={})

    assert str(exc_info.value) == (
        "Non-Windows path resolution requires DMGUARD_APP_ROOT and "
        "DMGUARD_DATA_ROOT; missing: DMGUARD_APP_ROOT, DMGUARD_DATA_ROOT"
    )


def test_resolve_paths_non_windows_requires_app_root():
    from dmguard.paths import resolve_paths

    with pytest.raises(ValueError) as exc_info:
        resolve_paths(
            platform="darwin",
            env={"DMGUARD_DATA_ROOT": "/tmp/dmguard-data"},
        )

    assert str(exc_info.value) == (
        "Non-Windows path resolution requires DMGUARD_APP_ROOT and "
        "DMGUARD_DATA_ROOT; missing: DMGUARD_APP_ROOT"
    )


def test_resolve_paths_non_windows_requires_data_root():
    from dmguard.paths import resolve_paths

    with pytest.raises(ValueError) as exc_info:
        resolve_paths(
            platform="darwin",
            env={"DMGUARD_APP_ROOT": "/tmp/dmguard-app"},
        )

    assert str(exc_info.value) == (
        "Non-Windows path resolution requires DMGUARD_APP_ROOT and "
        "DMGUARD_DATA_ROOT; missing: DMGUARD_DATA_ROOT"
    )


def test_resolved_paths_are_path_instances():
    from dmguard.paths import resolve_paths

    paths = resolve_paths(platform="win32", env={})

    assert isinstance(paths.program_files_dir, Path)
    assert isinstance(paths.program_data_dir, Path)
    assert isinstance(paths.db_path, Path)
    assert isinstance(paths.config_path, Path)
    assert isinstance(paths.secrets_path, Path)
    assert isinstance(paths.logs_dir, Path)
    assert isinstance(paths.tmp_dir, Path)


def test_exported_path_constants_are_path_instances():
    from dmguard import paths

    assert isinstance(paths.PROGRAM_FILES_DIR, Path)
    assert isinstance(paths.PROGRAM_DATA_DIR, Path)
    assert isinstance(paths.DB_PATH, Path)
    assert isinstance(paths.CONFIG_PATH, Path)
    assert isinstance(paths.SECRETS_PATH, Path)
    assert isinstance(paths.LOGS_DIR, Path)
    assert isinstance(paths.TMP_DIR, Path)


def test_exported_path_constants_respect_non_windows_env_override(monkeypatch):
    from dmguard import paths

    with monkeypatch.context() as context:
        context.setattr(paths.sys, "platform", "darwin")
        context.setenv("DMGUARD_APP_ROOT", "/tmp/dmguard-app")
        context.setenv("DMGUARD_DATA_ROOT", "/tmp/dmguard-data")

        reloaded_paths = importlib.reload(paths)

        assert reloaded_paths.PROGRAM_FILES_DIR == Path("/tmp/dmguard-app")
        assert reloaded_paths.PROGRAM_DATA_DIR == Path("/tmp/dmguard-data")
        assert reloaded_paths.DB_PATH == Path("/tmp/dmguard-data/state.db")
        assert reloaded_paths.CONFIG_PATH == Path("/tmp/dmguard-data/config.yaml")
        assert reloaded_paths.SECRETS_PATH == Path("/tmp/dmguard-data/secrets.bin")
        assert reloaded_paths.LOGS_DIR == Path("/tmp/dmguard-data/logs")
        assert reloaded_paths.TMP_DIR == Path("/tmp/dmguard-data/tmp")

    importlib.reload(paths)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="non-Windows only")
def test_importing_paths_without_non_windows_env_vars_fails_clearly(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DMGUARD_APP_ROOT", "DMGUARD_DATA_ROOT"}
    }
    env["PYTHONPATH"] = str(repo_root)

    result = subprocess.run(
        [sys.executable, "-c", "import dmguard.paths"],
        capture_output=True,
        check=False,
        cwd=repo_root,
        env=env,
        text=True,
    )

    assert result.returncode == 1
    assert "DMGUARD_APP_ROOT" in result.stderr
    assert "DMGUARD_DATA_ROOT" in result.stderr
