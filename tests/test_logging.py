import logging
from datetime import UTC, datetime

import httpx
import pytest

from forex_alert_bot.logging import configure_logging
from forex_alert_bot.news import MarketauxNewsProvider


@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
def test_provider_request_logs_do_not_expose_credentials(level, caplog) -> None:
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    previous_levels = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.setLevel(logging.NOTSET)
        with caplog.at_level(level):
            configure_logging(level)
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"data": []})
                )
            ) as client:
                provider = MarketauxNewsProvider("test-secret-marker", client=client)
                assert (
                    provider.fetch_news(
                        ["EUR/USD"], published_after=datetime(2026, 9, 10, tzinfo=UTC), limit=3
                    )
                    == []
                )
            logging.getLogger("httpcore.http11").debug("headers: test-secret-marker")
            logging.getLogger("forex_alert_bot.scheduler").info("Signal check started.")

        assert "test-secret-marker" not in caplog.text
        assert "api_token=" not in caplog.text
        assert "Signal check started." in caplog.text
    finally:
        for logger, previous_level in zip(loggers, previous_levels, strict=True):
            logger.setLevel(previous_level)
