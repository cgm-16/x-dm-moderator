from pathlib import Path
from typing import Final, Mapping
import re


PLACEHOLDER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\{\{([^{}]+)\}\}")
SUPPORTED_PLACEHOLDERS: Final[frozenset[str]] = frozenset(
    {
        "PUBLIC_HOSTNAME",
        "BACKEND_URL",
        "DEBUG_DASHBOARD_PORT",
        "ACME_EMAIL",
        "ACME_STORAGE_PATH",
        "TRAEFIK_LOG_PATH",
        "TRAEFIK_ROUTES_PATH",
    }
)


class UnknownPlaceholderError(ValueError):
    pass


class MissingPlaceholderValueError(ValueError):
    pass


def render_template(tpl_path: Path, vars: Mapping[str, object]) -> str:
    template = tpl_path.read_text()
    placeholders = [match.group(1) for match in PLACEHOLDER_PATTERN.finditer(template)]

    unknown_placeholders = sorted(
        {
            placeholder
            for placeholder in placeholders
            if placeholder not in SUPPORTED_PLACEHOLDERS
        }
    )
    if unknown_placeholders:
        unknown_placeholder = unknown_placeholders[0]
        raise UnknownPlaceholderError(f"Unknown placeholder: {unknown_placeholder}")

    missing_placeholders = sorted(
        {
            placeholder
            for placeholder in placeholders
            if placeholder in SUPPORTED_PLACEHOLDERS and placeholder not in vars
        }
    )
    if missing_placeholders:
        missing_placeholder = missing_placeholders[0]
        raise MissingPlaceholderValueError(
            f"Missing placeholder value: {missing_placeholder}"
        )

    def replace_placeholder(match: re.Match[str]) -> str:
        placeholder = match.group(1)
        return str(vars[placeholder])

    return PLACEHOLDER_PATTERN.sub(replace_placeholder, template)


__all__ = [
    "MissingPlaceholderValueError",
    "SUPPORTED_PLACEHOLDERS",
    "UnknownPlaceholderError",
    "render_template",
]
