"""Scheduled runtime for recurring Forex signal checks."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from forex_alert_bot.config import Settings
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.market_data import (
    MarketDataError,
    MarketDataProvider,
    MarketDataRateLimitError,
    create_market_data_provider,
)

logger = logging.getLogger(__name__)


def run_signal_check(
    settings: Settings,
    database: SQLiteLog | None = None,
    market_data_provider: MarketDataProvider | None = None,
) -> None:
    """Fetch configured market data without allowing provider failures to stop scheduling."""
    database = database or SQLiteLog(settings.database_path)
    run_id = database.start_run(dry_run=settings.dry_run)
    try:
        logger.info("Scheduled signal check started.")
        if settings.dry_run:
            logger.info("Dry run: no real alert was sent.")

        try:
            provider = market_data_provider or create_market_data_provider(
                settings.market_data_provider, settings.market_data_api_key
            )
        except MarketDataError as error:
            _record_market_data_error(database, run_id, error)
        else:
            _fetch_configured_candles(settings, database, run_id, provider)
        database.complete_run(run_id)
    except Exception as error:
        try:
            database.fail_run(run_id, stage="signal-check", error=error)
        except Exception:
            logger.exception("Unable to persist scheduled signal check failure.")
        logger.exception("Scheduled signal check failed.")
        raise


def _record_market_data_error(database: SQLiteLog, run_id: int, error: Exception) -> None:
    try:
        database.record_error(run_id, stage="market-data", error=error)
    except Exception:
        logger.exception("Unable to persist market-data fetch failure.")
    logger.warning("Market data fetch failed: %s", error)


def _fetch_configured_candles(
    settings: Settings,
    database: SQLiteLog,
    run_id: int,
    provider: MarketDataProvider,
) -> None:
    for pair in settings.market_data_pairs:
        for timeframe in settings.market_data_timeframes:
            try:
                candles = provider.fetch_candles(pair, timeframe)
            except MarketDataRateLimitError as error:
                _record_market_data_error(database, run_id, error)
                return
            except Exception as error:
                _record_market_data_error(database, run_id, error)
            else:
                logger.info("Fetched %s candles for %s at %s.", len(candles), pair, timeframe)


def create_scheduler(settings: Settings) -> BlockingScheduler:
    """Create the recurring signal-check scheduler for the configured local window."""
    timezone = ZoneInfo(settings.timezone)
    database = SQLiteLog(settings.database_path)
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        run_signal_check,
        trigger=OrTrigger(
            [
                CronTrigger(
                    minute="0,30",
                    hour=f"{settings.alert_window_start_hour}-{settings.alert_window_end_hour - 1}",
                    timezone=timezone,
                ),
                CronTrigger(
                    minute="0",
                    hour=str(settings.alert_window_end_hour),
                    timezone=timezone,
                ),
            ]
        ),
        args=[settings, database],
        id="signal-check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True,
    )
    return scheduler
