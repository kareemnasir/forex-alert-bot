"""Scheduled runtime for recurring Forex signal checks."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from forex_alert_bot.config import Settings

logger = logging.getLogger(__name__)


def run_signal_check(settings: Settings) -> None:
    """Log one scheduled signal-check run until signal processing is implemented."""
    logger.info("Scheduled signal check started.")
    if settings.dry_run:
        logger.info("Dry run: no real alert or network send was made.")
    else:
        logger.info("Signal checks are not implemented yet; no alert or network send was made.")


def create_scheduler(settings: Settings) -> BlockingScheduler:
    """Create the recurring signal-check scheduler for the configured local window."""
    timezone = ZoneInfo(settings.timezone)
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
        args=[settings],
        id="signal-check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True,
    )
    return scheduler
