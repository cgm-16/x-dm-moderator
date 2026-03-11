from pathlib import Path

import pytest


def write_template(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def template_vars() -> dict[str, str]:
    return {
        "PUBLIC_HOSTNAME": "example.duckdns.org",
        "BACKEND_URL": "http://127.0.0.1:8080",
        "DEBUG_DASHBOARD_PORT": "8081",
        "ACME_EMAIL": "ops@example.com",
        "ACME_STORAGE_PATH": "C:/ProgramData/XDMModerator/traefik/acme.json",
        "TRAEFIK_LOG_PATH": "C:/ProgramData/XDMModerator/logs/traefik.log",
    }


def test_render_template_substitutes_supported_placeholders(tmp_path: Path) -> None:
    from dmguard.templates import render_template

    template_path = write_template(
        tmp_path / "traefik-static.yml.tpl",
        "\n".join(
            [
                "host={{PUBLIC_HOSTNAME}}",
                "backend={{BACKEND_URL}}",
                "dashboard={{DEBUG_DASHBOARD_PORT}}",
                "email={{ACME_EMAIL}}",
                "storage={{ACME_STORAGE_PATH}}",
                "log={{TRAEFIK_LOG_PATH}}",
                "repeat={{PUBLIC_HOSTNAME}}",
            ]
        ),
    )

    rendered = render_template(template_path, template_vars())

    assert rendered == "\n".join(
        [
            "host=example.duckdns.org",
            "backend=http://127.0.0.1:8080",
            "dashboard=8081",
            "email=ops@example.com",
            "storage=C:/ProgramData/XDMModerator/traefik/acme.json",
            "log=C:/ProgramData/XDMModerator/logs/traefik.log",
            "repeat=example.duckdns.org",
        ]
    )


def test_render_template_raises_for_unknown_placeholder(tmp_path: Path) -> None:
    from dmguard.templates import UnknownPlaceholderError, render_template

    template_path = write_template(
        tmp_path / "traefik-static.yml.tpl",
        "host={{PUBLIC_HOSTNAME}}\ninvalid={{UNKNOWN_KEY}}",
    )

    with pytest.raises(UnknownPlaceholderError, match="UNKNOWN_KEY"):
        render_template(template_path, template_vars())


def test_render_template_raises_for_missing_placeholder_value(tmp_path: Path) -> None:
    from dmguard.templates import MissingPlaceholderValueError, render_template

    template_path = write_template(
        tmp_path / "traefik-static.yml.tpl",
        "host={{PUBLIC_HOSTNAME}}\nemail={{ACME_EMAIL}}",
    )
    vars_without_email = template_vars()
    del vars_without_email["ACME_EMAIL"]

    with pytest.raises(MissingPlaceholderValueError, match="ACME_EMAIL"):
        render_template(template_path, vars_without_email)


def test_routes_templates_render_independently(tmp_path: Path) -> None:
    from dmguard.templates import render_template

    normal_template = write_template(
        tmp_path / "routes-normal.yml.tpl",
        "rule=Host(`{{PUBLIC_HOSTNAME}}`)\nservice={{BACKEND_URL}}",
    )
    debug_template = write_template(
        tmp_path / "routes-debug.yml.tpl",
        "dashboard=:{{DEBUG_DASHBOARD_PORT}}\nlog={{TRAEFIK_LOG_PATH}}",
    )

    rendered_normal = render_template(normal_template, template_vars())
    rendered_debug = render_template(debug_template, template_vars())

    assert (
        rendered_normal
        == "rule=Host(`example.duckdns.org`)\nservice=http://127.0.0.1:8080"
    )
    assert (
        rendered_debug
        == "dashboard=:8081\nlog=C:/ProgramData/XDMModerator/logs/traefik.log"
    )


def test_render_template_ignores_unused_values(tmp_path: Path) -> None:
    from dmguard.templates import render_template

    template_path = write_template(
        tmp_path / "routes-normal.yml.tpl",
        "rule=Host(`{{PUBLIC_HOSTNAME}}`)",
    )
    values = template_vars()
    values["UNUSED_VALUE"] = "ignored"

    rendered = render_template(template_path, values)

    assert rendered == "rule=Host(`example.duckdns.org`)"
