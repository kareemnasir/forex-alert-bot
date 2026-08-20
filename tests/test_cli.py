import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from forex_alert_bot.config import Settings
from forex_alert_bot.telegram import TelegramNotifierError


def test_module_runs_one_signal_check_in_dry_run_mode(tmp_path) -> None:
    database_path = tmp_path / "forex-alert-bot.sqlite3"
    environment = os.environ | {
        "DATABASE_PATH": str(database_path),
        "DRY_RUN": "false",
        "LOG_LEVEL": "INFO",
        "MARKET_DATA_API_KEY": "",
        "NEWS_API_KEY": "",
        "OLLAMA_API_KEY": "",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
    }

    result = subprocess.run(
        [sys.executable, "-m", "forex_alert_bot", "--run-once", "--dry-run"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0
    assert "Run 1 completed" in result.stdout
    assert "Candidates: 0" in result.stdout
    assert "Technical decisions: 1" in result.stdout
    assert "Final decisions: 1" in result.stdout
    assert "Sent alerts: 0" in result.stdout
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT status, dry_run FROM runs").fetchall() == [
            ("completed", 1)
        ]
        assert connection.execute("SELECT COUNT(*) FROM alerts").fetchone() == (0,)


def test_module_does_not_run_alerts_when_dry_run_is_disabled(tmp_path) -> None:
    environment = os.environ | {
        "DATABASE_PATH": str(tmp_path / "forex-alert-bot.sqlite3"),
        "DRY_RUN": "false",
        "LOG_LEVEL": "INFO",
    }

    result = subprocess.run(
        [sys.executable, "-m", "forex_alert_bot"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0
    assert "No command selected" in result.stderr
    assert "signal checks are not implemented yet" not in result.stderr
    assert "application scaffold" not in result.stderr.lower()


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


def test_schedule_command_starts_scheduler_without_blocking(monkeypatch) -> None:
    from forex_alert_bot import cli

    settings = Settings()
    created_with: list[Settings] = []
    started: list[bool] = []

    class SchedulerStub:
        def start(self) -> None:
            started.append(True)

    def create_scheduler_stub(value: Settings) -> SchedulerStub:
        created_with.append(value)
        return SchedulerStub()

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_scheduler", create_scheduler_stub)

    assert cli.main(["--schedule"]) == 0
    assert created_with == [settings]
    assert started == [True]


def test_schedule_dry_run_forwards_dry_run_settings_to_scheduler(monkeypatch) -> None:
    from forex_alert_bot import cli

    settings = Settings(dry_run=False)
    created_with: list[Settings] = []

    class SchedulerStub:
        def start(self) -> None:
            pass

    def create_scheduler_stub(value: Settings) -> SchedulerStub:
        created_with.append(value)
        return SchedulerStub()

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "create_scheduler", create_scheduler_stub)

    assert cli.main(["--schedule", "--dry-run"]) == 0
    assert created_with == [Settings(dry_run=True)]


def test_run_once_executes_complete_pipeline_once_without_starting_scheduler(
    monkeypatch, capsys, tmp_path
) -> None:
    from forex_alert_bot import cli

    settings = Settings(
        dry_run=False,
        database_path=tmp_path / "forex-alert-bot.sqlite3",
    )
    runs: list[Settings] = []

    def run_signal_check_stub(value: Settings):
        runs.append(value)
        return SimpleNamespace(
            run_id=27,
            candidates=(object(), object()),
            technical_decisions=(object(),),
            final_decisions=(object(),),
            sent_alert_ids=(41,),
        )

    def unexpected_scheduler(_settings: Settings):
        raise AssertionError("One-shot execution must not create the scheduler")

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "run_signal_check", run_signal_check_stub)
    monkeypatch.setattr(cli, "create_scheduler", unexpected_scheduler)

    assert cli.main(["--run-once"]) == 0
    assert runs == [settings]
    assert capsys.readouterr().out.splitlines() == [
        "Run 27 completed",
        "Candidates: 2",
        "Technical decisions: 1",
        "Final decisions: 1",
        "Sent alerts: 1",
    ]


def test_run_once_dry_run_safely_overrides_live_configuration(monkeypatch, tmp_path) -> None:
    from forex_alert_bot import cli

    settings = Settings(
        dry_run=False,
        database_path=tmp_path / "forex-alert-bot.sqlite3",
    )
    received_settings: list[Settings] = []

    def run_signal_check_stub(value: Settings):
        received_settings.append(value)
        return SimpleNamespace(
            run_id=1,
            candidates=(),
            technical_decisions=(),
            final_decisions=(),
            sent_alert_ids=(),
        )

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "run_signal_check", run_signal_check_stub)

    assert cli.main(["--run-once", "--dry-run"]) == 0
    assert received_settings == [Settings(dry_run=True, database_path=settings.database_path)]


def test_run_once_preserves_configured_dry_run_mode(monkeypatch, tmp_path) -> None:
    from forex_alert_bot import cli

    settings = Settings(
        dry_run=True,
        database_path=tmp_path / "forex-alert-bot.sqlite3",
    )
    received_settings: list[Settings] = []

    def run_signal_check_stub(value: Settings):
        received_settings.append(value)
        return SimpleNamespace(
            run_id=1,
            candidates=(),
            technical_decisions=(),
            final_decisions=(),
            sent_alert_ids=(),
        )

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "run_signal_check", run_signal_check_stub)

    assert cli.main(["--run-once"]) == 0
    assert received_settings == [settings]


def test_run_once_failure_returns_safe_nonzero_error(monkeypatch, capsys, tmp_path) -> None:
    from forex_alert_bot import cli

    secret = "provider-secret-payload"
    settings = Settings(database_path=tmp_path / "forex-alert-bot.sqlite3")
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "run_signal_check",
        lambda _settings: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    assert cli.main(["--run-once"]) == 1
    output = capsys.readouterr()
    assert "Signal check failed; inspect the run's Error Records for details." in output.err
    assert secret not in output.err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--run-once", "--schedule"],
        ["--telegram-test", "--inspect-recent"],
        ["--inspect-recent", "--inspect-run", "1"],
    ],
)
def test_incompatible_commands_are_rejected(arguments, capsys, monkeypatch, tmp_path) -> None:
    from forex_alert_bot import cli

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=tmp_path / "forex-alert-bot.sqlite3"),
    )

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--dry-run"],
        ["--telegram-test", "--dry-run"],
        ["--inspect-recent", "--dry-run"],
        ["--inspect-run", "1", "--dry-run"],
    ],
)
def test_dry_run_override_requires_a_signal_execution_command(
    arguments, capsys, monkeypatch, tmp_path
) -> None:
    from forex_alert_bot import cli

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=tmp_path / "forex-alert-bot.sqlite3"),
    )

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    assert "--dry-run requires --run-once or --schedule" in capsys.readouterr().err
