"""Minimal Telegram Bot API notifier."""

from __future__ import annotations

from typing import Protocol

import httpx

from forex_alert_bot.config import Settings

TEST_MESSAGE = "Forex alert bot Telegram test message."
TELEGRAM_API_URL = "https://api.telegram.org/bot{bot_token}/sendMessage"


class TelegramNotifierError(RuntimeError):
    """Raised when a Telegram alert cannot be sent."""


class TelegramHttpClient(Protocol):
    """The small subset of an HTTP client used by the Telegram notifier."""

    def post(self, url: str, *, data: dict[str, str], timeout: float) -> httpx.Response: ...


class TelegramNotifier:
    """Send messages to one configured Telegram chat."""

    def __init__(
        self,
        bot_token: str | None,
        chat_id: str | None,
        *,
        client: TelegramHttpClient | None = None,
    ) -> None:
        if not bot_token:
            raise TelegramNotifierError("TELEGRAM_BOT_TOKEN must be configured")
        if not chat_id:
            raise TelegramNotifierError("TELEGRAM_CHAT_ID must be configured")

        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx

    def send_test_message(self) -> None:
        """Send the single message used to verify Telegram configuration."""
        try:
            response = self._client.post(
                TELEGRAM_API_URL.format(bot_token=self._bot_token),
                data={"chat_id": self._chat_id, "text": TEST_MESSAGE},
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise TelegramNotifierError("Telegram API request failed") from error

        try:
            payload = response.json()
        except ValueError as error:
            raise TelegramNotifierError("Telegram API response was invalid") from error

        if not isinstance(payload, dict):
            raise TelegramNotifierError("Telegram API response was invalid")
        if payload.get("ok") is not True:
            raise TelegramNotifierError("Telegram API rejected the test message")


def send_telegram_test_message(settings: Settings) -> None:
    """Send one Telegram test message using the configured credentials."""
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    notifier.send_test_message()
