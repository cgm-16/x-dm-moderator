from pathlib import Path
import sys

from dmguard.config import AppConfig, ClassifierBackend, load_app_config


FAKE_CLASSIFIER_BASE_CMD = (
    sys.executable,
    "-m",
    "dmguard.classifier_fake",
)
LLAVAGUARD_CLASSIFIER_BASE_CMD = (
    sys.executable,
    "-m",
    "dmguard.classifier_llavaguard",
)


def build_classifier_cmd(backend: ClassifierBackend) -> tuple[str, ...]:
    if backend == "llavaguard":
        return LLAVAGUARD_CLASSIFIER_BASE_CMD

    return FAKE_CLASSIFIER_BASE_CMD


def build_runtime_classifier_cmd(config: AppConfig) -> tuple[str, ...]:
    return build_classifier_cmd(config.classifier_backend)


def load_runtime_classifier_cmd(config_path: Path) -> tuple[str, ...]:
    try:
        config = load_app_config(config_path)
    except FileNotFoundError:
        return FAKE_CLASSIFIER_BASE_CMD

    return build_runtime_classifier_cmd(config)


def build_fake_classifier_cmd(
    *,
    force_safe: bool = False,
    force_unsafe: bool = False,
) -> tuple[str, ...]:
    if force_safe and force_unsafe:
        raise ValueError("Only one forced fake classifier outcome can be selected")

    cmd = list(FAKE_CLASSIFIER_BASE_CMD)
    if force_safe:
        cmd.append("--force-safe")
    if force_unsafe:
        cmd.append("--force-unsafe")

    return tuple(cmd)


__all__ = [
    "FAKE_CLASSIFIER_BASE_CMD",
    "LLAVAGUARD_CLASSIFIER_BASE_CMD",
    "build_classifier_cmd",
    "build_fake_classifier_cmd",
    "build_runtime_classifier_cmd",
    "load_runtime_classifier_cmd",
]
