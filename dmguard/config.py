from pathlib import Path

from pydantic import BaseModel, ConfigDict
import yaml

from dmguard.paths import CONFIG_PATH


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    debug: bool
    log_level: str
    port: int = 8080
    host: str = "127.0.0.1"
    debug_dashboard_port: int = 8081
    public_hostname: str
    acme_email: str


def load_app_config(path: Path | None = None) -> AppConfig:
    config_path = path or CONFIG_PATH

    with config_path.open(encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file) or {}

    return AppConfig.model_validate(raw_config)


__all__ = ["AppConfig", "load_app_config"]
