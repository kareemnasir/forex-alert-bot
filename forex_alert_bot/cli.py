"""Command-line entry point for the Forex alert bot."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from dataclasses import replace
from typing import Sequence

from forex_alert_bot.config import load_settings
from forex_alert_bot.inspection import (
    InspectionError,
    SQLiteInspector,
    format_recent_runs,
    format_run,
)
from forex_alert_bot.logging import configure_logging
from forex_alert_bot.scheduler import create_scheduler, run_signal_check
from forex_alert_bot.telegram import TelegramNotifierError, send_telegram_test_message

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Run exactly one explicitly selected operator command."""
    parser = argparse.ArgumentParser(description="Forex alert bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without performing live alert actions.",
    )
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument(
        "--telegram-test",
        action="store_true",
        help="Send one test message to the configured Telegram chat.",
    )
    commands.add_argument(
        "--run-once",
        action="store_true",
        help="Execute one complete signal check, then exit.",
    )
    commands.add_argument(
        "--schedule",
        action="store_true",
        help="Start the recurring signal-check scheduler.",
    )
    commands.add_argument(
        "--inspect-recent",
        action="store_true",
        help="Read the most recent Runs from SQLite.",
    )
    commands.add_argument(
        "--inspect-run",
        type=int,
        metavar="RUN_ID",
        help="Read one Run and its recorded decision flow from SQLite.",
    )
    arguments = parser.parse_args(argv)
    if arguments.dry_run and not (arguments.run_once or arguments.schedule):
        parser.error("--dry-run requires --run-once or --schedule")

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

    if arguments.run_once:
        try:
            result = run_signal_check(settings)
        except Exception:
            print(
                "Signal check failed; inspect the run's Error Records for details.",
                file=sys.stderr,
            )
            return 1
        print(f"Run {result.run_id} completed")
        print(f"Candidates: {len(result.candidates)}")
        print(f"Technical decisions: {len(result.technical_decisions)}")
        print(f"Final decisions: {len(result.final_decisions)}")
        print(f"Sent alerts: {len(result.sent_alert_ids)}")
        return 0

    if arguments.inspect_recent or arguments.inspect_run is not None:
        inspector = SQLiteInspector(settings.database_path)
        try:
            output = (
                format_recent_runs(inspector.recent_runs())
                if arguments.inspect_recent
                else format_run(inspector.run(arguments.inspect_run))
            )
        except InspectionError as error:
            print(error, file=sys.stderr)
            return 1
        print(output)
        return 0

    if arguments.schedule:
        scheduler = create_scheduler(settings)
        logger.info("Starting signal-check scheduler.")
        previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

        def shutdown_scheduler(_signum, _frame) -> None:
            logger.info("Stopping signal-check scheduler.")
            if not scheduler.running:
                raise SystemExit(0)
            scheduler.shutdown(wait=True)

        signal.signal(signal.SIGTERM, shutdown_scheduler)
        try:
            scheduler.start()
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
        return 0

    print(
        "No command selected; use --run-once, --schedule, --telegram-test, "
        "--inspect-recent, or --inspect-run.",
        file=sys.stderr,
    )
    return 0
