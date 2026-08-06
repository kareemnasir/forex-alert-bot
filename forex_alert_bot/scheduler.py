"""Scheduled runtime for recurring Forex signal checks."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from forex_alert_bot.config import Settings
from forex_alert_bot.database import SQLiteLog

logger = logging.getLogger(__name__)


def run_signal_check(settings: Settings, database: SQLiteLog | None = None) -> None:
    """Log one scheduled signal-check run until signal processing is implemented."""
    database = database or SQLiteLog(settings.database_path)
    run_id = database.start_run(dry_run=settings.dry_run)
    try:
        logger.info("Scheduled signal check started.")
        if settings.dry_run:
            logger.info("Dry run: no real alert or network send was made.")
        else:
            logger.info("Signal checks are not implemented yet; no alert or network send was made.")
        database.complete_run(run_id)
    except Exception as error:
        try:
            database.fail_run(run_id, stage="signal-check", error=error)
        except Exception:
            logger.exception("Unable to persist scheduled signal check failure.")
        logger.exception("Scheduled signal check failed.")
        raise


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
