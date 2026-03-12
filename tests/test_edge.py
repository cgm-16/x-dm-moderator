from pathlib import Path

import pytest


def test_write_routes_atomically_replaces_target_file(tmp_path: Path) -> None:
    from dmguard.edge import write_routes_atomically

    target = tmp_path / "routes.yml"
    target.write_text("http:\n  routers:\n    old: {}\n", encoding="utf-8")

    write_routes_atomically(
        "http:\n  routers:\n    webhook:\n      rule: Host(`example.duckdns.org`)\n",
        target,
    )

    assert target.read_text(encoding="utf-8") == (
        "http:\n  routers:\n    webhook:\n      rule: Host(`example.duckdns.org`)\n"
    )
    assert sorted(path.name for path in tmp_path.iterdir()) == ["routes.yml"]


def test_write_routes_atomically_raises_before_touching_target(tmp_path: Path) -> None:
    from dmguard.edge import InvalidYamlError, write_routes_atomically

    target = tmp_path / "routes.yml"
    original_content = "http:\n  routers:\n    current: {}\n"
    target.write_text(original_content, encoding="utf-8")

    with pytest.raises(InvalidYamlError):
        write_routes_atomically("http:\n  routers: [\n", target)

    assert target.read_text(encoding="utf-8") == original_content
    assert sorted(path.name for path in tmp_path.iterdir()) == ["routes.yml"]


def test_write_routes_atomically_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    from dmguard.edge import InvalidYamlError, write_routes_atomically

    target = tmp_path / "routes.yml"
    original_content = "http:\n  routers:\n    current: {}\n"
    target.write_text(original_content, encoding="utf-8")

    with pytest.raises(InvalidYamlError, match="mapping"):
        write_routes_atomically("- item1\n- item2\n", target)

    assert target.read_text(encoding="utf-8") == original_content
    assert sorted(path.name for path in tmp_path.iterdir()) == ["routes.yml"]


def test_generate_traefik_service_def_contains_required_servy_fields() -> None:
    from dmguard.edge import generate_traefik_service_def

    service_def = generate_traefik_service_def()

    assert service_def == {
        "name": "XDMModeratorTraefik",
        "displayName": "XDMModerator Traefik",
        "description": "Traefik reverse proxy for XDMModerator",
        "path": "C:/Program Files/XDMModerator/traefik/traefik.exe",
        "startupDir": "C:/Program Files/XDMModerator/traefik",
        "params": "--configFile=C:/ProgramData/XDMModerator/traefik/traefik-static.yml",
        "startupType": "Automatic",
        "stdout": "C:/ProgramData/XDMModerator/logs/traefik-service.out.log",
        "stderr": "C:/ProgramData/XDMModerator/logs/traefik-service.err.log",
    }


def test_generate_dmguard_service_def_contains_dependency_on_traefik() -> None:
    from dmguard.edge import generate_dmguard_service_def

    service_def = generate_dmguard_service_def()

    assert service_def == {
        "name": "XDMModerator",
        "displayName": "XDMModerator",
        "description": "XDMModerator application service",
        "path": "C:/Program Files/XDMModerator/dmguard.exe",
        "startupDir": "C:/Program Files/XDMModerator",
        "startupType": "Automatic",
        "stdout": "C:/ProgramData/XDMModerator/logs/dmguard-service.out.log",
        "stderr": "C:/ProgramData/XDMModerator/logs/dmguard-service.err.log",
        "deps": ["XDMModeratorTraefik"],
    }
