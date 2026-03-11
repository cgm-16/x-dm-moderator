from pathlib import Path

import pytest


def make_setup_state():
    from dmguard.setup_state import SetupState, StageStatus

    return SetupState(
        last_command="setup --verbose",
        effective_args={
            "debug": True,
            "public_hostname": "dmguard.duckdns.org",
        },
        stages={
            "preflight": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:00Z",
                finished_at="2026-03-11T12:00:01Z",
                artifacts=["C:/ProgramData/XDMModerator/setup_state.json"],
            ),
            "tls": StageStatus(
                status="pending",
                started_at=None,
                finished_at=None,
                artifacts=[],
            ),
        },
        updated_at="2026-03-11T12:00:01Z",
    )


def test_load_setup_state_returns_none_for_missing_file(tmp_path: Path) -> None:
    from dmguard.setup_state import load_setup_state

    state_path = tmp_path / "setup_state.json"

    assert load_setup_state(state_path) is None


def test_save_and_load_setup_state_round_trip(tmp_path: Path) -> None:
    from dmguard.setup_state import SetupState, load_setup_state, save_setup_state

    state_path = tmp_path / "setup_state.json"
    expected = make_setup_state()

    save_setup_state(expected, state_path)
    loaded = load_setup_state(state_path)

    assert loaded == expected
    assert isinstance(loaded, SetupState)


def test_save_setup_state_uses_atomic_replace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dmguard import setup_state

    state_path = tmp_path / "setup_state.json"
    expected = make_setup_state()
    captured: dict[str, Path] = {}
    original_replace = setup_state.os.replace

    def recording_replace(src: str | bytes | Path, dst: str | bytes | Path) -> None:
        captured["src"] = Path(src)
        captured["dst"] = Path(dst)
        original_replace(src, dst)

    monkeypatch.setattr(setup_state.os, "replace", recording_replace)

    setup_state.save_setup_state(expected, state_path)

    assert captured["dst"] == state_path
    assert captured["src"] != state_path
    assert captured["src"].parent == state_path.parent
    assert captured["src"].name.startswith(f".{state_path.name}.")
    assert captured["src"].suffix == ".tmp"
    assert not captured["src"].exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["setup_state.json"]
