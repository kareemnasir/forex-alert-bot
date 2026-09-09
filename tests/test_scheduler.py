import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from forex_alert_bot.config import Settings
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.market_data import MarketDataRateLimitError
from forex_alert_bot.scheduler import create_scheduler, run_signal_check


def test_scheduler_uses_default_local_window_and_half_hour_cadence(tmp_path) -> None:
    settings = Settings(database_path=tmp_path / "forex-alert-bot.sqlite3")
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


def test_scheduler_limits_weekends_to_the_forex_session(tmp_path) -> None:
    settings = Settings(database_path=tmp_path / "forex-alert-bot.sqlite3")
    scheduler = create_scheduler(settings)
    job = scheduler.get_job("signal-check")

    assert job is not None
    timezone = ZoneInfo("America/Detroit")
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 7, 16, 59, tzinfo=timezone)
    ) == datetime(2026, 8, 7, 17, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 7, 17, 1, tzinfo=timezone)
    ) == datetime(2026, 8, 9, 17, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 8, 12, 0, tzinfo=timezone)
    ) == datetime(2026, 8, 9, 17, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 9, 16, 59, tzinfo=timezone)
    ) == datetime(2026, 8, 9, 17, 0, tzinfo=timezone)
    assert job.trigger.get_next_fire_time(
        None, datetime(2026, 8, 9, 22, 1, tzinfo=timezone)
    ) == datetime(2026, 8, 10, 7, 0, tzinfo=timezone)


def test_scheduler_clamps_configured_windows_to_forex_session_boundaries(tmp_path) -> None:
    timezone = ZoneInfo("America/Detroit")
    cases = (
        (
            18,
            22,
            datetime(2026, 8, 7, 12, 0, tzinfo=timezone),
            datetime(2026, 8, 9, 18, 0, tzinfo=timezone),
        ),
        (
            7,
            16,
            datetime(2026, 8, 9, 12, 0, tzinfo=timezone),
            datetime(2026, 8, 10, 7, 0, tzinfo=timezone),
        ),
        (
            17,
            22,
            datetime(2026, 8, 7, 16, 59, tzinfo=timezone),
            datetime(2026, 8, 7, 17, 0, tzinfo=timezone),
        ),
    )

    for start_hour, end_hour, now, expected in cases:
        scheduler = create_scheduler(
            Settings(
                alert_window_start_hour=start_hour,
                alert_window_end_hour=end_hour,
                database_path=tmp_path / f"forex-alert-bot-{start_hour}-{end_hour}.sqlite3",
            )
        )
        job = scheduler.get_job("signal-check")

        assert job is not None
        assert job.trigger.get_next_fire_time(None, now) == expected


def test_scheduler_uses_configured_timezone_and_window(tmp_path) -> None:
    scheduler = create_scheduler(
        Settings(
            timezone="UTC",
            alert_window_start_hour=8,
            alert_window_end_hour=21,
            database_path=tmp_path / "forex-alert-bot.sqlite3",
        )
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


def test_dry_run_callback_logs_that_no_alert_was_sent(caplog, tmp_path) -> None:
    caplog.set_level("INFO")

    run_signal_check(Settings(dry_run=True, database_path=tmp_path / "forex-alert-bot.sqlite3"))

    assert "Signal check started." in caplog.text
    assert "Dry run: no real alert was sent." in caplog.text


def test_scheduled_signal_check_records_a_completed_run(tmp_path) -> None:
    database_path = tmp_path / "forex-alert-bot.sqlite3"

    run_signal_check(Settings(dry_run=True, database_path=database_path))

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("SELECT status, dry_run, finished_at FROM runs").fetchall()

    assert len(rows) == 1
    assert rows[0][0:2] == ("completed", 1)
    assert rows[0][2] is not None


def test_scheduler_records_market_data_failures_without_crashing(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    settings = Settings(
        database_path=database.path,
        market_data_pairs=("EUR/USD",),
        market_data_timeframes=("15min",),
    )

    class RateLimitedProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            raise MarketDataRateLimitError("API credits exhausted")

    run_signal_check(settings, database=database, market_data_provider=RateLimitedProvider())

    assert database.get_run(1)["status"] == "completed"
    assert database.get_errors(1) == [
        {
            "run_id": 1,
            "stage": "market-data",
            "error_type": "MarketDataRateLimitError",
            "message": "API credits exhausted",
        }
    ]


def test_scheduler_safely_records_unexpected_provider_fetch_failures(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    settings = Settings(
        database_path=database.path,
        market_data_pairs=("EUR/USD",),
        market_data_timeframes=("15min",),
    )

    class BrokenProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            raise RuntimeError("provider connection broke")

    run_signal_check(settings, database=database, market_data_provider=BrokenProvider())

    assert database.get_run(1)["status"] == "completed"
    assert database.get_errors(1)[0]["error_type"] == "RuntimeError"


def test_scheduler_stops_remaining_fetches_after_a_rate_limit(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    settings = Settings(
        database_path=database.path,
        market_data_pairs=("EUR/USD", "GBP/USD"),
        market_data_timeframes=("15min", "1h"),
    )
    calls: list[tuple[str, str]] = []

    class RateLimitedProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            calls.append((pair, timeframe))
            raise MarketDataRateLimitError("API credits exhausted")

    run_signal_check(settings, database=database, market_data_provider=RateLimitedProvider())

    assert calls == [("EUR/USD", "15min")]
    assert database.get_run(1)["status"] == "completed"
    assert len(database.get_errors(1)) == 1


def test_scheduler_fetches_each_configured_pair_and_timeframe(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    settings = Settings(
        database_path=database.path,
        market_data_pairs=("EUR/USD", "GBP/USD"),
        market_data_timeframes=("15min", "1h"),
    )
    calls: list[tuple[str, str]] = []

    class RecordingProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            calls.append((pair, timeframe))
            return []

    run_signal_check(settings, database=database, market_data_provider=RecordingProvider())

    assert calls == [
        ("EUR/USD", "15min"),
        ("EUR/USD", "1h"),
        ("GBP/USD", "15min"),
        ("GBP/USD", "1h"),
    ]
    assert database.get_run(1)["status"] == "completed"
    assert database.get_errors(1) == []


def test_scheduled_callback_delegates_orchestration_to_pipeline(monkeypatch, tmp_path) -> None:
    from forex_alert_bot import scheduler

    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    settings = Settings(database_path=database.path)
    runs: list[object] = []

    class PipelineStub:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["settings"] is settings
            assert kwargs["database"] is database

        def run(self) -> None:
            runs.append("ran")

    monkeypatch.setattr(scheduler, "SignalPipeline", PipelineStub)

    run_signal_check(settings, database=database)

    assert runs == ["ran"]
