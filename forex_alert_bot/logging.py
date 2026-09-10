"""Logging configuration for command-line runs."""

import logging


def configure_logging(level: str) -> None:
    """Configure consistent console logging for the application."""
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=level,
    )
    # Request URLs can contain Marketaux/Telegram credentials; transport debug
    # records can also contain headers. Keep application diagnostics enabled.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
