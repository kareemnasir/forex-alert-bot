"""Logging configuration for command-line runs."""

import logging


def configure_logging(level: str) -> None:
    """Configure consistent console logging for the application."""
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=level,
    )
