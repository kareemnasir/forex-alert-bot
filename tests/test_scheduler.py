import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from forex_alert_bot.config import Settings
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.scheduler import create_scheduler, run_signal_check


def test_scheduler_uses_default_local_window_and_half_hour_cadence() -> None:
    settings = Settings()
    scheduler = create_scheduler(settings)

    job = scheduler.get_job("signal-check")

    assert job is not None
    assert isinstance(job.args[1], SQLiteLog)
    assert job.args[1].path == settings.database_path
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 60
    timezone = ZoneInfo("America/Detroit")
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 6, 6, 59, tzinfo=timezone)
    ) == datetime(2026, 8, 6, 7, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        datetime(2026, 8, 6, 7, 0, tzinfo=timezone),
        datetime(2026, 8, 6, 7, 0, tzinfo=timezone),
    ) == datetime(2026, 8, 6, 7, 30, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 6, 21, 59, tzinfo=timezone)
    ) == datetime(2026, 8, 6, 22, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        datetime(2026, 8, 6, 22, 0, tzinfo=timezone),
        datetime(2026, 8, 6, 22, 1, tzinfo=timezone),
    ) == datetime(2026, 8, 7, 7, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 6, 22, 31, tzinfo=timezone)
    ) == datetime(2026, 8, 7, 7, 0, tzinfo=timezone)


def test_scheduler_uses_configured_timezone_and_window() -> None:
    scheduler = create_scheduler(
        Settings(timezone="UTC", alert_window_start_hour=8, alert_window_end_hour=21)
    )

    job = scheduler.get_job("signal-check")

    assert job is not None
    timezone = ZoneInfo("UTC")
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 6, 7, 59, tzinfo=timezone)
    ) == datetime(2026, 8, 6, 8, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 6, 20, 59, tzinfo=timezone)
    ) == datetime(2026, 8, 6, 21, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        datetime(2026, 8, 6, 21, 0, tzinfo=timezone),
        datetime(2026, 8, 6, 21, 1, tzinfo=timezone),
    ) == datetime(2026, 8, 7, 8, 0, tzinfo=timezone)


def test_dry_run_callback_logs_that_no_alert_or_network_send_was_made(caplog) -> None:
    caplog.set_level("INFO")

    run_signal_check(Settings(dry_run=True))

    assert "Scheduled signal check started." in caplog.text
    assert "Dry run: no real alert or network send was made." in caplog.text


def test_scheduled_signal_check_records_a_completed_run(tmp_path) -> None:
    database_path = tmp_path / "forex-alert-bot.sqlite3"

    run_signal_check(Settings(dry_run=True, database_path=database_path))

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("SELECT status, dry_run, finished_at FROM runs").fetchall()

    assert len(rows) == 1
    assert rows[0][0:2] == ("completed", 1)
    assert rows[0][2] is not None


def test_failed_scheduled_signal_check_records_failed_run_and_error(tmp_path, monkeypatch) -> None:
    from forex_alert_bot import scheduler

    database_path = tmp_path / "forex-alert-bot.sqlite3"

    def raise_signal_check_error(_: str) -> None:
        raise RuntimeError("signal check failed")

    monkeypatch.setattr(scheduler.logger, "info", raise_signal_check_error)

    with pytest.raises(RuntimeError, match="signal check failed"):
        run_signal_check(Settings(database_path=database_path))

    with sqlite3.connect(database_path) as connection:
        run = connection.execute("SELECT status FROM runs").fetchone()
        error = connection.execute("SELECT stage, error_type, message FROM errors").fetchone()

    assert run == ("failed",)
    assert error == ("signal-check", "RuntimeError", "signal check failed")


def test_completion_failure_attempts_to_record_a_failed_run() -> None:
    settings = Settings()
    recorded_failures: list[Exception] = []

    class DatabaseStub:
        def start_run(self, *, dry_run: bool) -> int:
            return 1

        def complete_run(self, run_id: int) -> None:
            raise RuntimeError("database completion failed")

        def fail_run(self, run_id: int, *, stage: str, error: Exception) -> None:
            recorded_failures.append(error)

    with pytest.raises(RuntimeError, match="database completion failed"):
        run_signal_check(settings, database=DatabaseStub())

    assert recorded_failures[0].args == ("database completion failed",)


def test_failure_persistence_does_not_mask_signal_check_error(monkeypatch) -> None:
    settings = Settings()

    class DatabaseStub:
        def start_run(self, *, dry_run: bool) -> int:
            return 1

        def complete_run(self, run_id: int) -> None:
            pass

        def fail_run(self, run_id: int, *, stage: str, error: Exception) -> None:
            raise ValueError("database rejected failure record")

    def raise_signal_check_error(_: str) -> None:
        raise RuntimeError("signal check failed")

    from forex_alert_bot import scheduler

    monkeypatch.setattr(scheduler.logger, "info", raise_signal_check_error)

    with pytest.raises(RuntimeError, match="signal check failed"):
        run_signal_check(settings, database=DatabaseStub())
