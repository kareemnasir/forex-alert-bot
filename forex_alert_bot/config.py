"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
DEFAULT_DRY_RUN = True
DEFAULT_TIMEZONE = "America/Detroit"
DEFAULT_ALERT_WINDOW_START_HOUR = 7
DEFAULT_ALERT_WINDOW_END_HOUR = 22
DEFAULT_DATABASE_PATH = Path("data/forex-alert-bot.sqlite3")
DEFAULT_MARKET_DATA_PROVIDER = "twelve_data"
DEFAULT_MARKET_DATA_PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY")
DEFAULT_MARKET_DATA_TIMEFRAMES = ("15min", "1h")
DEFAULT_ALERT_COOLDOWN_MINUTES = 120
DEFAULT_LOG_LEVEL = "INFO"
_FOREX_PAIR_PATTERN = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
_SUPPORTED_TIMEFRAMES = {
    "1min",
    "5min",
    "15min",
    "30min",
    "45min",
    "1h",
    "2h",
    "4h",
    "8h",
    "1day",
    "1week",
    "1month",
}


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the alert bot scaffold."""

    dry_run: bool = DEFAULT_DRY_RUN
    timezone: str = DEFAULT_TIMEZONE
    alert_window_start_hour: int = DEFAULT_ALERT_WINDOW_START_HOUR
    alert_window_end_hour: int = DEFAULT_ALERT_WINDOW_END_HOUR
    database_path: Path = DEFAULT_DATABASE_PATH
    market_data_provider: str = DEFAULT_MARKET_DATA_PROVIDER
    market_data_api_key: str | None = None
    market_data_pairs: tuple[str, ...] = DEFAULT_MARKET_DATA_PAIRS
    market_data_timeframes: tuple[str, ...] = DEFAULT_MARKET_DATA_TIMEFRAMES
    alert_cooldown_minutes: int = DEFAULT_ALERT_COOLDOWN_MINUTES
    log_level: str = DEFAULT_LOG_LEVEL
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Settings:
        """Build settings from an environment mapping without reading files."""
        timezone = environment.get("APP_TIMEZONE", DEFAULT_TIMEZONE)
        try:
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("APP_TIMEZONE must be a valid IANA timezone") from error

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

        market_data_provider = environment.get(
            "MARKET_DATA_PROVIDER", DEFAULT_MARKET_DATA_PROVIDER
        ).lower()
        if market_data_provider != "twelve_data":
            raise ValueError("MARKET_DATA_PROVIDER must be twelve_data")

        return cls(
            dry_run=_parse_boolean(environment.get("DRY_RUN", str(DEFAULT_DRY_RUN))),
            timezone=timezone,
            alert_window_start_hour=alert_window_start_hour,
            alert_window_end_hour=alert_window_end_hour,
            database_path=Path(environment.get("DATABASE_PATH", str(DEFAULT_DATABASE_PATH))),
            market_data_provider=market_data_provider,
            market_data_api_key=environment.get("MARKET_DATA_API_KEY"),
            market_data_pairs=_parse_pairs(
                environment.get("MARKET_DATA_PAIRS", ",".join(DEFAULT_MARKET_DATA_PAIRS))
            ),
            market_data_timeframes=_parse_timeframes(
                environment.get("MARKET_DATA_TIMEFRAMES", ",".join(DEFAULT_MARKET_DATA_TIMEFRAMES))
            ),
            alert_cooldown_minutes=_parse_alert_cooldown_minutes(
                environment.get("ALERT_COOLDOWN_MINUTES", str(DEFAULT_ALERT_COOLDOWN_MINUTES))
            ),
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


def _parse_pairs(value: str) -> tuple[str, ...]:
    pairs = tuple(item.strip().upper() for item in value.split(",") if item.strip())
    if not pairs or any(_FOREX_PAIR_PATTERN.fullmatch(pair) is None for pair in pairs):
        raise ValueError("MARKET_DATA_PAIRS must be a comma-separated list like EUR/USD")
    return pairs


def _parse_timeframes(value: str) -> tuple[str, ...]:
    timeframes = tuple(item.strip() for item in value.split(",") if item.strip())
    if not timeframes or any(timeframe not in _SUPPORTED_TIMEFRAMES for timeframe in timeframes):
        raise ValueError("MARKET_DATA_TIMEFRAMES contains an unsupported Twelve Data interval")
    return timeframes


def _parse_alert_cooldown_minutes(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as error:
        raise ValueError("ALERT_COOLDOWN_MINUTES must be a nonnegative integer") from error
    if minutes < 0:
        raise ValueError("ALERT_COOLDOWN_MINUTES must be a nonnegative integer")
    return minutes
