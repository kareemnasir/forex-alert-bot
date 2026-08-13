import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from forex_alert_bot.config import Settings
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.market_data import MarketDataRateLimitError
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


def test_dry_run_callback_logs_that_no_alert_was_sent(caplog) -> None:
    caplog.set_level("INFO")

    run_signal_check(Settings(dry_run=True))

    assert "Scheduled signal check started." in caplog.text
    assert "Dry run: no real alert was sent." in caplog.text


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

        def record_error(self, run_id: int, *, stage: str, error: Exception) -> None:
            pass

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


def test_scheduler_records_news_failures_without_crashing(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    settings = Settings(
        database_path=database.path,
        market_data_pairs=("EUR/USD",),
        market_data_timeframes=("15min",),
    )

    class EmptyMarketDataProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            return []

    class BrokenNewsProvider:
        def fetch_news(self, *args: object, **kwargs: object) -> list[object]:
            raise RuntimeError("news provider unavailable")

    run_signal_check(
        settings,
        database=database,
        market_data_provider=EmptyMarketDataProvider(),
        news_provider=BrokenNewsProvider(),
    )

    assert database.get_run(1)["status"] == "completed"
    assert database.get_errors(1) == [
        {
            "run_id": 1,
            "stage": "news",
            "error_type": "RuntimeError",
            "message": "news provider unavailable",
        }
    ]


def test_scheduler_fetches_news_once_without_calling_sentiment(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    settings = Settings(
        database_path=database.path,
        market_data_pairs=("EUR/USD", "USD/JPY"),
        market_data_timeframes=("15min",),
    )
    news_calls: list[tuple[tuple[str, ...], int]] = []

    class EmptyMarketDataProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            return []

    class RecordingNewsProvider:
        def fetch_news(
            self,
            pairs: tuple[str, ...],
            *,
            published_after: datetime,
            limit: int,
        ) -> list[object]:
            news_calls.append((pairs, limit))
            return []

        def analyze_sentiment(self) -> None:
            raise AssertionError("sentiment must remain out of scope for issue #28")

    run_signal_check(
        settings,
        database=database,
        market_data_provider=EmptyMarketDataProvider(),
        news_provider=RecordingNewsProvider(),
    )

    assert news_calls == [(("EUR/USD", "USD/JPY"), 10)]
    assert database.get_run(1)["status"] == "completed"


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


def test_scheduler_keeps_running_when_market_data_error_logging_fails() -> None:
    completions: list[int] = []

    class DatabaseStub:
        def start_run(self, *, dry_run: bool) -> int:
            return 1

        def record_error(self, run_id: int, *, stage: str, error: Exception) -> None:
            raise RuntimeError("database unavailable")

        def complete_run(self, run_id: int) -> None:
            completions.append(run_id)

        def fail_run(self, run_id: int, *, stage: str, error: Exception) -> None:
            raise AssertionError("recoverable fetch failure should not fail the run")

    class FailingProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            raise RuntimeError("provider unavailable")

    run_signal_check(
        Settings(market_data_pairs=("EUR/USD",), market_data_timeframes=("15min",)),
        database=DatabaseStub(),
        market_data_provider=FailingProvider(),
    )

    assert completions == [1]


def test_scheduler_keeps_running_when_news_error_logging_fails() -> None:
    completions: list[int] = []

    class DatabaseStub:
        def start_run(self, *, dry_run: bool) -> int:
            return 1

        def record_error(self, run_id: int, *, stage: str, error: Exception) -> None:
            raise RuntimeError("database unavailable")

        def complete_run(self, run_id: int) -> None:
            completions.append(run_id)

        def fail_run(self, run_id: int, *, stage: str, error: Exception) -> None:
            raise AssertionError("recoverable fetch failure should not fail the run")

    class EmptyMarketDataProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[object]:
            return []

    class FailingNewsProvider:
        def fetch_news(self, *args: object, **kwargs: object) -> list[object]:
            raise RuntimeError("news provider unavailable")

    run_signal_check(
        Settings(market_data_pairs=("EUR/USD",), market_data_timeframes=("15min",)),
        database=DatabaseStub(),
        market_data_provider=EmptyMarketDataProvider(),
        news_provider=FailingNewsProvider(),
    )

    assert completions == [1]


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
