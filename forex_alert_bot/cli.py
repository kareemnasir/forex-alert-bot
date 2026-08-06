"""Command-line entry point for the Forex alert bot."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from typing import Sequence

from forex_alert_bot.config import load_settings
from forex_alert_bot.logging import configure_logging
from forex_alert_bot.scheduler import create_scheduler
from forex_alert_bot.telegram import TelegramNotifierError, send_telegram_test_message

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the application scaffold and report the selected runtime mode."""
    parser = argparse.ArgumentParser(description="Forex alert bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without performing live alert actions.",
    )
    parser.add_argument(
        "--telegram-test",
        action="store_true",
        help="Send one test message to the configured Telegram chat.",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Start the recurring signal-check scheduler.",
    )
    arguments = parser.parse_args(argv)

    settings = load_settings()
    if arguments.dry_run:
        settings = replace(settings, dry_run=True)

    configure_logging(settings.log_level)
    if arguments.telegram_test:
        try:
            send_telegram_test_message(settings)
        except TelegramNotifierError as error:
            logger.error("Telegram test failed: %s", error)
            return 1
        logger.info("Telegram test message sent.")
        return 0

    if arguments.schedule:
        scheduler = create_scheduler(settings)
        logger.info("Starting signal-check scheduler.")
        scheduler.start()
        return 0

    if settings.dry_run:
        logger.info("Dry run enabled; no signal check is executed.")
    else:
        logger.info("Application scaffold started; signal checks are not implemented yet.")
    return 0
