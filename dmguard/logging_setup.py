from pathlib import Path
import logging

from dmguard.config import AppConfig
from dmguard.paths import LOGS_DIR


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def resolve_log_level(log_level: str) -> int:
    try:
        return logging.getLevelNamesMapping()[log_level.upper()]
    except KeyError as error:
        raise ValueError(f"Unsupported log level: {log_level}") from error


def reset_logger_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def configure_file_logger(name: str, log_path: Path, level: int) -> logging.Logger:
    logger = logging.getLogger(name)
    reset_logger_handlers(logger)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    return logger


def setup_logging(config: AppConfig) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    level = resolve_log_level(config.log_level)

    configure_file_logger("dmguard", LOGS_DIR / "dmguard.log", level)
    configure_file_logger("classifier", LOGS_DIR / "classifier.log", level)


__all__ = ["setup_logging"]
