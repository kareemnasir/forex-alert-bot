"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
DEFAULT_DRY_RUN = True
DEFAULT_TIMEZONE = "America/Detroit"
DEFAULT_ALERT_WINDOW_START_HOUR = 7
DEFAULT_ALERT_WINDOW_END_HOUR = 22
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the alert bot scaffold."""

    dry_run: bool = DEFAULT_DRY_RUN
    timezone: str = DEFAULT_TIMEZONE
    alert_window_start_hour: int = DEFAULT_ALERT_WINDOW_START_HOUR
    alert_window_end_hour: int = DEFAULT_ALERT_WINDOW_END_HOUR
    log_level: str = DEFAULT_LOG_LEVEL
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Settings:
        """Build settings from an environment mapping without reading files."""
        alert_window_start_hour = _parse_hour(
            "ALERT_WINDOW_START_HOUR",
            environment.get("ALERT_WINDOW_START_HOUR", str(DEFAULT_ALERT_WINDOW_START_HOUR)),
        )
        alert_window_end_hour = _parse_hour(
            "ALERT_WINDOW_END_HOUR",
            environment.get("ALERT_WINDOW_END_HOUR", str(DEFAULT_ALERT_WINDOW_END_HOUR)),
        )
        if alert_window_start_hour >= alert_window_end_hour:
            raise ValueError("ALERT_WINDOW_START_HOUR must be earlier than ALERT_WINDOW_END_HOUR")

        return cls(
            dry_run=_parse_boolean(environment.get("DRY_RUN", str(DEFAULT_DRY_RUN))),
            timezone=environment.get("APP_TIMEZONE", DEFAULT_TIMEZONE),
            alert_window_start_hour=alert_window_start_hour,
            alert_window_end_hour=alert_window_end_hour,
            log_level=environment.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
            telegram_bot_token=environment.get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=environment.get("TELEGRAM_CHAT_ID"),
        )


def load_settings() -> Settings:
    """Load a local .env file without overriding explicit environment values."""
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    return Settings.from_environment(os.environ)


def _parse_boolean(value: str) -> bool:
    normalized_value = value.strip().lower()
    if normalized_value in _TRUE_VALUES:
        return True
    if normalized_value in _FALSE_VALUES:
        return False
    raise ValueError("DRY_RUN must be one of: true, false, 1, 0, yes, no, on, off")


def _parse_hour(variable: str, value: str) -> int:
    try:
        hour = int(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be an integer between 0 and 23") from error

    if not 0 <= hour <= 23:
        raise ValueError(f"{variable} must be between 0 and 23")
    return hour
