import importlib
from pathlib import Path


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
