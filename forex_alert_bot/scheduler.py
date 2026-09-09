"""Scheduled runtime for recurring Forex signal checks."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from forex_alert_bot.config import Settings
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.market_data import MarketDataProvider
from forex_alert_bot.news import NewsProvider
from forex_alert_bot.pipeline import (
    AlertNotifier,
    PipelineRunResult,
    SentimentAnalyzer,
    SignalPipeline,
)

logger = logging.getLogger(__name__)

FOREX_WEEK_OPEN_HOUR = 17
FOREX_WEEK_CLOSE_HOUR = 17


def run_signal_check(
    settings: Settings,
    database: SQLiteLog | None = None,
    market_data_provider: MarketDataProvider | None = None,
    news_provider: NewsProvider | None = None,
    sentiment_analyzer: SentimentAnalyzer | None = None,
    notifier: AlertNotifier | None = None,
) -> PipelineRunResult:
    """Delegate one Run to the end-to-end signal pipeline."""
    database = database or SQLiteLog(settings.database_path)
    logger.info("Signal check started.")
    if settings.dry_run:
        logger.info("Dry run: no real alert was sent.")
    return SignalPipeline(
        settings=settings,
        database=database,
        market_data_provider=market_data_provider,
        news_provider=news_provider,
        sentiment_analyzer=sentiment_analyzer,
        notifier=notifier,
    ).run()


def create_scheduler(settings: Settings) -> BlockingScheduler:
    """Create the recurring signal-check scheduler for the configured local window."""
    timezone = ZoneInfo(settings.timezone)
    database = SQLiteLog(settings.database_path)
    scheduler = BlockingScheduler(timezone=timezone)
    triggers = [
        *_window_triggers(
            day_of_week="mon-thu",
            start_hour=settings.alert_window_start_hour,
            end_hour=settings.alert_window_end_hour,
            timezone=timezone,
        ),
        *_window_triggers(
            day_of_week="fri",
            start_hour=settings.alert_window_start_hour,
            end_hour=min(settings.alert_window_end_hour, FOREX_WEEK_CLOSE_HOUR),
            timezone=timezone,
        ),
        *_window_triggers(
            day_of_week="sun",
            start_hour=max(settings.alert_window_start_hour, FOREX_WEEK_OPEN_HOUR),
            end_hour=settings.alert_window_end_hour,
            timezone=timezone,
        ),
    ]
    scheduler.add_job(
        run_signal_check,
        trigger=OrTrigger(triggers),
        args=[settings, database],
        id="signal-check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True,
    )
    return scheduler


def _window_triggers(
    *,
    day_of_week: str,
    start_hour: int,
    end_hour: int,
    timezone: ZoneInfo,
) -> list[CronTrigger]:
    if start_hour > end_hour:
        return []
    triggers = []
    if start_hour < end_hour:
        triggers.append(
            CronTrigger(
                day_of_week=day_of_week,
                minute="0,30",
                hour=f"{start_hour}-{end_hour - 1}",
                timezone=timezone,
            )
        )
    triggers.append(
        CronTrigger(
            day_of_week=day_of_week,
            minute="0",
            hour=str(end_hour),
            timezone=timezone,
        )
    )
    return triggers
