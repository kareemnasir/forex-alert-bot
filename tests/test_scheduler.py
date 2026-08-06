from datetime import datetime
from zoneinfo import ZoneInfo

from forex_alert_bot.config import Settings
from forex_alert_bot.scheduler import create_scheduler, run_signal_check


def test_scheduler_uses_default_local_window_and_half_hour_cadence() -> None:
    scheduler = create_scheduler(Settings())

    job = scheduler.get_job("signal-check")

    assert job is not None
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
