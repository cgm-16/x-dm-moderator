from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from dmguard.paths import PROGRAM_DATA_DIR
from dmguard.secrets import SECRET_KEYS


DEFAULT_SETUP_LOG_PATH = PROGRAM_DATA_DIR / "setup.log"
GENERIC_SECRET_LABELS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer",
        "client_secret",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)

SECRET_LABEL_PATTERN = "|".join(
    sorted(
        (re.escape(label) for label in SECRET_KEYS | GENERIC_SECRET_LABELS),
        key=len,
        reverse=True,
    )
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    rf'(?P<label>["\']?(?:{SECRET_LABEL_PATTERN})["\']?\s*(?:=|:)\s*)'
    rf'(?P<quote>["\']?)(?P<value>[^\s,"\']+(?:\s+(?!\w+\s*(?:=|:))[^\s,"\']+)*)(?P=quote)',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SetupLogger:
    path: Path = DEFAULT_SETUP_LOG_PATH

    def redact(self, message: str) -> str:
        return SECRET_ASSIGNMENT_PATTERN.sub(self._replace_secret_value, message)

    def log(self, message: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"{timestamp} {self.redact(message)}\n"

        with self.path.open("a", encoding="utf-8") as log_file:
            log_file.write(line)

    @staticmethod
    def _replace_secret_value(match: re.Match[str]) -> str:
        quote = match.group("quote")
        return f"{match.group('label')}{quote}[REDACTED]{quote}"


__all__ = ["DEFAULT_SETUP_LOG_PATH", "SetupLogger"]
