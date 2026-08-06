import pytest

from forex_alert_bot.config import Settings, load_settings


def test_settings_use_safe_defaults() -> None:
    settings = Settings.from_environment({})

    assert settings.dry_run is True
    assert settings.timezone == "America/Detroit"
    assert settings.log_level == "INFO"


def test_settings_read_environment_values() -> None:
    settings = Settings.from_environment(
        {
            "DRY_RUN": "false",
            "APP_TIMEZONE": "UTC",
            "LOG_LEVEL": "debug",
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "12345",
        }
    )

    assert settings.dry_run is False
    assert settings.timezone == "UTC"
    assert settings.log_level == "DEBUG"
    assert settings.telegram_bot_token == "test-token"
    assert settings.telegram_chat_id == "12345"


def test_settings_reject_invalid_boolean_values() -> None:
    with pytest.raises(ValueError, match="DRY_RUN"):
        Settings.from_environment({"DRY_RUN": "sometimes"})


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
