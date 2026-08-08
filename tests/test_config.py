import pytest

from forex_alert_bot.config import Settings, load_settings


def test_settings_use_safe_defaults() -> None:
    settings = Settings.from_environment({})

    assert settings.dry_run is True
    assert settings.timezone == "America/Detroit"
    assert settings.alert_window_start_hour == 7
    assert settings.alert_window_end_hour == 22
    assert settings.database_path.name == "forex-alert-bot.sqlite3"
    assert settings.market_data_provider == "twelve_data"
    assert settings.market_data_api_key is None
    assert settings.market_data_pairs == ("EUR/USD", "GBP/USD", "USD/JPY")
    assert settings.market_data_timeframes == ("15min", "1h")
    assert settings.log_level == "INFO"


def test_settings_read_environment_values() -> None:
    settings = Settings.from_environment(
        {
            "DRY_RUN": "false",
            "APP_TIMEZONE": "UTC",
            "ALERT_WINDOW_START_HOUR": "8",
            "ALERT_WINDOW_END_HOUR": "21",
            "LOG_LEVEL": "debug",
            "MARKET_DATA_PROVIDER": "twelve_data",
            "MARKET_DATA_API_KEY": "market-data-token",
            "MARKET_DATA_PAIRS": "EUR/USD, AUD/USD",
            "MARKET_DATA_TIMEFRAMES": "5min, 1h",
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "12345",
        }
    )

    assert settings.dry_run is False
    assert settings.timezone == "UTC"
    assert settings.alert_window_start_hour == 8
    assert settings.alert_window_end_hour == 21
    assert settings.log_level == "DEBUG"
    assert settings.market_data_provider == "twelve_data"
    assert settings.market_data_api_key == "market-data-token"
    assert settings.market_data_pairs == ("EUR/USD", "AUD/USD")
    assert settings.market_data_timeframes == ("5min", "1h")
    assert settings.telegram_bot_token == "test-token"
    assert settings.telegram_chat_id == "12345"


def test_settings_read_database_path() -> None:
    settings = Settings.from_environment({"DATABASE_PATH": "var/logs/alerts.sqlite3"})

    assert str(settings.database_path) == "var/logs/alerts.sqlite3"


def test_settings_reject_invalid_boolean_values() -> None:
    with pytest.raises(ValueError, match="DRY_RUN"):
        Settings.from_environment({"DRY_RUN": "sometimes"})


@pytest.mark.parametrize("timezone", ["Not/A_Timezone", ""])
def test_settings_reject_invalid_timezones(timezone: str) -> None:
    with pytest.raises(ValueError, match="APP_TIMEZONE"):
        Settings.from_environment({"APP_TIMEZONE": timezone})


@pytest.mark.parametrize(
    ("environment", "variable"),
    [
        ({"ALERT_WINDOW_START_HOUR": "morning"}, "ALERT_WINDOW_START_HOUR"),
        ({"ALERT_WINDOW_END_HOUR": "24"}, "ALERT_WINDOW_END_HOUR"),
        (
            {"ALERT_WINDOW_START_HOUR": "22", "ALERT_WINDOW_END_HOUR": "7"},
            "ALERT_WINDOW_START_HOUR",
        ),
    ],
)
def test_settings_reject_invalid_alert_windows(environment: dict[str, str], variable: str) -> None:
    with pytest.raises(ValueError, match=variable):
        Settings.from_environment(environment)


@pytest.mark.parametrize(
    ("environment", "variable"),
    [
        ({"MARKET_DATA_PROVIDER": "other"}, "MARKET_DATA_PROVIDER"),
        ({"MARKET_DATA_PAIRS": "EURUSD"}, "MARKET_DATA_PAIRS"),
        ({"MARKET_DATA_TIMEFRAMES": "10min"}, "MARKET_DATA_TIMEFRAMES"),
    ],
)
def test_settings_reject_invalid_market_data_configuration(
    environment: dict[str, str], variable: str
) -> None:
    with pytest.raises(ValueError, match=variable):
        Settings.from_environment(environment)


def test_loader_uses_environment_values_over_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "DRY_RUN=false\nAPP_TIMEZONE=UTC\nLOG_LEVEL=warning\n"
        "TELEGRAM_BOT_TOKEN=dotenv-token\nTELEGRAM_CHAT_ID=dotenv-chat\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "environment-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    settings = load_settings()

    assert settings.dry_run is True
    assert settings.timezone == "UTC"
    assert settings.log_level == "WARNING"
    assert settings.telegram_bot_token == "environment-token"
    assert settings.telegram_chat_id == "dotenv-chat"
