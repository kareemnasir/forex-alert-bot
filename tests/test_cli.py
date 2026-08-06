import os
import subprocess
import sys

from forex_alert_bot.config import Settings
from forex_alert_bot.telegram import TelegramNotifierError


def test_module_runs_in_dry_run_mode() -> None:
    environment = os.environ | {"DRY_RUN": "false", "LOG_LEVEL": "INFO"}

    result = subprocess.run(
        [sys.executable, "-m", "forex_alert_bot", "--dry-run"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0
    assert "Dry run enabled" in result.stderr


def test_module_does_not_run_alerts_when_dry_run_is_disabled() -> None:
    environment = os.environ | {"DRY_RUN": "false", "LOG_LEVEL": "INFO"}

    result = subprocess.run(
        [sys.executable, "-m", "forex_alert_bot"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0
    assert "signal checks are not implemented yet" in result.stderr


def test_telegram_test_command_reports_clear_delivery_failures(monkeypatch, caplog) -> None:
    from forex_alert_bot import cli

    def raise_delivery_error(settings: Settings) -> None:
        raise TelegramNotifierError("Telegram API request failed")

    monkeypatch.setattr(cli, "load_settings", lambda: Settings())
    monkeypatch.setattr(cli, "send_telegram_test_message", raise_delivery_error)

    assert cli.main(["--telegram-test"]) == 1
    assert "Telegram test failed: Telegram API request failed" in caplog.text


def test_telegram_test_command_sends_one_message(monkeypatch) -> None:
    from forex_alert_bot import cli

    sent_settings: list[Settings] = []
    settings = Settings(telegram_bot_token="test-token", telegram_chat_id="12345")
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "send_telegram_test_message", sent_settings.append)

    assert cli.main(["--telegram-test"]) == 0
    assert sent_settings == [settings]
