from pathlib import Path

import pytest


def make_setup_state():
    from dmguard.setup_state import SetupState, StageStatus

    return SetupState(
        last_command="setup --verbose",
        effective_args={
            "debug": True,
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
                started_at="2026-03-11T12:00:00Z",
                finished_at="2026-03-11T12:00:01Z",
                artifacts=["C:/ProgramData/XDMModerator/setup_state.json"],
            ),
            "local_config": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:01Z",
                finished_at="2026-03-11T12:00:02Z",
                artifacts=["C:/ProgramData/XDMModerator/config.yaml"],
            ),
            "x_auth": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:02Z",
                finished_at="2026-03-11T12:00:03Z",
                artifacts=["C:/ProgramData/XDMModerator/secrets.bin"],
            ),
            "duckdns": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:03Z",
                finished_at="2026-03-11T12:00:04Z",
                artifacts=["C:/ProgramData/XDMModerator/duckdns.txt"],
            ),
            "traefik": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:04Z",
                finished_at="2026-03-11T12:00:05Z",
                artifacts=["C:/ProgramData/XDMModerator/traefik/routes.yml"],
            ),
            "tls": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:05Z",
                finished_at="2026-03-11T12:00:06Z",
                artifacts=["C:/ProgramData/XDMModerator/traefik/acme.json"],
            ),
            "public_reachability": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:06Z",
                finished_at="2026-03-11T12:00:07Z",
                artifacts=[],
            ),
            "app_service": StageStatus(
                status="pending",
                started_at=None,
                finished_at=None,
                artifacts=[],
            ),
            "warmup": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:07Z",
                finished_at="2026-03-11T12:00:08Z",
                artifacts=[],
            ),
            "x_webhook": StageStatus(
                status="done",
                started_at="2026-03-11T12:00:08Z",
                finished_at="2026-03-11T12:00:09Z",
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


def test_compute_args_hash_is_stable_for_equivalent_dict_order() -> None:
    from dmguard.setup_state import compute_args_hash

    first = {
        "public_hostname": "dmguard.duckdns.org",
        "debug": True,
        "port": 8080,
    }
    second = {
        "port": 8080,
        "debug": True,
        "public_hostname": "dmguard.duckdns.org",
    }

    assert compute_args_hash(first) == compute_args_hash(second)


def test_invalidate_changed_stages_returns_empty_for_unchanged_args() -> None:
    from dmguard.setup_state import invalidate_changed_stages

    state = make_setup_state()
    unchanged_args = dict(state.effective_args)
    unchanged_statuses = {
        name: status.model_copy(deep=True) for name, status in state.stages.items()
    }

    assert invalidate_changed_stages(state, unchanged_args) == []
    assert state.effective_args == unchanged_args
    assert state.stages == unchanged_statuses


def test_invalidate_changed_stages_resets_affected_stage_and_downstream() -> None:
    from dmguard.setup_state import invalidate_changed_stages

    state = make_setup_state()

    invalidated = invalidate_changed_stages(
        state,
        {
            **state.effective_args,
            "public_hostname": "safety-filter.duckdns.org",
        },
    )

    assert invalidated == [
        "local_config",
        "x_auth",
        "duckdns",
        "traefik",
        "tls",
        "public_reachability",
        "app_service",
        "warmup",
        "x_webhook",
    ]
    assert state.effective_args["public_hostname"] == "safety-filter.duckdns.org"
    assert state.stages["preflight"].status == "done"

    for stage_name in invalidated:
        stage = state.stages[stage_name]
        assert stage.status == "pending"
        assert stage.started_at is None
        assert stage.finished_at is None
        assert stage.artifacts == []


def test_describe_verbose_stage_changes_mentions_changed_arg_and_skipped_stage() -> (
    None
):
    from dmguard.setup_state import describe_verbose_stage_changes

    state = make_setup_state()

    messages = describe_verbose_stage_changes(
        state,
        {
            **state.effective_args,
            "public_hostname": "safety-filter.duckdns.org",
        },
    )

    assert any(
        "local_config" in message and "public_hostname" in message
        for message in messages
    )
    assert any(
        "preflight" in message and "already done" in message for message in messages
    )


def test_invalidate_changed_stages_handles_removed_arg() -> None:
    from dmguard.setup_state import invalidate_changed_stages

    state = make_setup_state()
    args_without_acme_email = {
        k: v for k, v in state.effective_args.items() if k != "acme_email"
    }

    invalidated = invalidate_changed_stages(state, args_without_acme_email)

    assert "tls" in invalidated
    assert "preflight" not in invalidated
    assert "acme_email" not in state.effective_args


def test_invalidate_changed_stages_uses_preflight_for_unknown_arg() -> None:
    from dmguard.setup_state import invalidate_changed_stages

    state = make_setup_state()

    invalidated = invalidate_changed_stages(
        state,
        {
            **state.effective_args,
            "operator_region": "kr-seoul",
        },
    )

    assert invalidated == list(state.stages)
    for stage in state.stages.values():
        assert stage.status == "pending"
