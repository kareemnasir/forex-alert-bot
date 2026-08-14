"""Application configuration loaded from environment variables."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from forex_alert_bot.strategies import (
    BREAKOUT_STRATEGY,
    MEAN_REVERSION_STRATEGY,
    TREND_PULLBACK_STRATEGY,
)

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
DEFAULT_TECHNICAL_STRATEGIES = (
    TREND_PULLBACK_STRATEGY,
    BREAKOUT_STRATEGY,
    MEAN_REVERSION_STRATEGY,
)
DEFAULT_NEWS_PROVIDER = "marketaux"
DEFAULT_NEWS_MAX_AGE_HOURS = 24
DEFAULT_NEWS_MAX_ITEMS = 10
DEFAULT_OLLAMA_HOST = "https://ollama.com"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30.0
DEFAULT_OLLAMA_MAX_HEADLINES = 10
DEFAULT_OLLAMA_RETRY_COUNT = 1
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
_SUPPORTED_TECHNICAL_STRATEGIES = frozenset(DEFAULT_TECHNICAL_STRATEGIES)


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
    technical_strategies: tuple[str, ...] = DEFAULT_TECHNICAL_STRATEGIES
    news_provider: str = DEFAULT_NEWS_PROVIDER
    news_api_key: str | None = None
    news_max_age_hours: int = DEFAULT_NEWS_MAX_AGE_HOURS
    news_max_items: int = DEFAULT_NEWS_MAX_ITEMS
    ollama_api_key: str | None = None
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str | None = None
    ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    ollama_max_headlines: int = DEFAULT_OLLAMA_MAX_HEADLINES
    ollama_retry_count: int = DEFAULT_OLLAMA_RETRY_COUNT
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

        news_provider = environment.get("NEWS_PROVIDER", DEFAULT_NEWS_PROVIDER).lower()
        if news_provider != "marketaux":
            raise ValueError("NEWS_PROVIDER must be marketaux")

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
            technical_strategies=_parse_technical_strategies(
                environment.get(
                    "TECHNICAL_STRATEGIES",
                    ",".join(DEFAULT_TECHNICAL_STRATEGIES),
                )
            ),
            news_provider=news_provider,
            news_api_key=environment.get("NEWS_API_KEY"),
            news_max_age_hours=_parse_positive_integer(
                "NEWS_MAX_AGE_HOURS",
                environment.get("NEWS_MAX_AGE_HOURS", str(DEFAULT_NEWS_MAX_AGE_HOURS)),
            ),
            news_max_items=_parse_positive_integer(
                "NEWS_MAX_ITEMS",
                environment.get("NEWS_MAX_ITEMS", str(DEFAULT_NEWS_MAX_ITEMS)),
            ),
            ollama_api_key=environment.get("OLLAMA_API_KEY"),
            ollama_host=environment.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/"),
            ollama_model=environment.get("OLLAMA_MODEL") or None,
            ollama_timeout_seconds=_parse_positive_float(
                "OLLAMA_TIMEOUT_SECONDS",
                environment.get("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS)),
            ),
            ollama_max_headlines=_parse_positive_integer(
                "OLLAMA_MAX_HEADLINES",
                environment.get("OLLAMA_MAX_HEADLINES", str(DEFAULT_OLLAMA_MAX_HEADLINES)),
            ),
            ollama_retry_count=_parse_ollama_retry_count(
                environment.get("OLLAMA_RETRY_COUNT", str(DEFAULT_OLLAMA_RETRY_COUNT))
            ),
            alert_cooldown_minutes=_parse_nonnegative_integer(
                "ALERT_COOLDOWN_MINUTES",
                environment.get("ALERT_COOLDOWN_MINUTES", str(DEFAULT_ALERT_COOLDOWN_MINUTES)),
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


def _parse_technical_strategies(value: str) -> tuple[str, ...]:
    strategies = tuple(
        dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip())
    )
    if not strategies or any(
        strategy not in _SUPPORTED_TECHNICAL_STRATEGIES for strategy in strategies
    ):
        raise ValueError(
            "TECHNICAL_STRATEGIES must contain trend-pullback, breakout, or mean-reversion"
        )
    return strategies


def _parse_positive_integer(variable: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"{variable} must be a positive integer")
    return parsed


def _parse_nonnegative_integer(variable: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be a nonnegative integer") from error
    if parsed < 0:
        raise ValueError(f"{variable} must be a nonnegative integer")
    return parsed


def _parse_ollama_retry_count(value: str) -> int:
    parsed = _parse_nonnegative_integer("OLLAMA_RETRY_COUNT", value)
    if parsed > 1:
        raise ValueError("OLLAMA_RETRY_COUNT must be 0 or 1")
    return parsed


def _parse_positive_float(variable: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be a positive number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{variable} must be a positive number")
    return parsed
