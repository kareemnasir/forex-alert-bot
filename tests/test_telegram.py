import httpx
import pytest

from forex_alert_bot.telegram import TelegramNotifier, TelegramNotifierError


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def post(self, url: str, *, data: dict[str, str], timeout: float) -> "SuccessfulResponse":
        self.calls.append((url, data, timeout))
        return SuccessfulResponse()


class SuccessfulResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, bool]:
        return {"ok": True}


class RejectedResponse(SuccessfulResponse):
    def json(self) -> dict[str, bool]:
        return {"ok": False}


class RejectedClient:
    def post(self, url: str, *, data: dict[str, str], timeout: float) -> RejectedResponse:
        return RejectedResponse()


class FailingClient:
    def post(self, url: str, *, data: dict[str, str], timeout: float) -> SuccessfulResponse:
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("connection failed", request=request)


class InvalidResponse(SuccessfulResponse):
    def json(self) -> dict[str, bool]:
        raise ValueError("invalid JSON")


class InvalidResponseClient:
    def post(self, url: str, *, data: dict[str, str], timeout: float) -> InvalidResponse:
        return InvalidResponse()


class NonObjectResponse(SuccessfulResponse):
    def json(self) -> list[bool]:
        return [True]


class NonObjectResponseClient:
    def post(self, url: str, *, data: dict[str, str], timeout: float) -> NonObjectResponse:
        return NonObjectResponse()


def test_notifier_sends_one_message_to_configured_chat() -> None:
    client = RecordingClient()
    notifier = TelegramNotifier("test-token", "12345", client=client)

    notifier.send_test_message()

    assert client.calls == [
        (
            "https://api.telegram.org/bottest-token/sendMessage",
            {"chat_id": "12345", "text": "Forex alert bot Telegram test message."},
            10.0,
        )
    ]


def test_notifier_sends_a_formatted_alert_message() -> None:
    client = RecordingClient()
    notifier = TelegramNotifier("test-token", "12345", client=client)

    notifier.send_alert("EUR/USD BUY Watch\nManual decision only.")

    assert client.calls == [
        (
            "https://api.telegram.org/bottest-token/sendMessage",
            {
                "chat_id": "12345",
                "text": "EUR/USD BUY Watch\nManual decision only.",
            },
            10.0,
        )
    ]


@pytest.mark.parametrize(
    ("bot_token", "chat_id", "missing_setting"),
    [(None, "12345", "TELEGRAM_BOT_TOKEN"), ("test-token", None, "TELEGRAM_CHAT_ID")],
)
def test_notifier_explains_missing_telegram_configuration(
    bot_token: str | None, chat_id: str | None, missing_setting: str
) -> None:
    with pytest.raises(TelegramNotifierError, match=missing_setting):
        TelegramNotifier(bot_token, chat_id)


def test_notifier_rejects_unsuccessful_telegram_api_responses() -> None:
    notifier = TelegramNotifier("test-token", "12345", client=RejectedClient())

    with pytest.raises(TelegramNotifierError, match="rejected"):
        notifier.send_test_message()


def test_notifier_hides_bot_token_when_the_http_request_fails() -> None:
    bot_token = "test-token"
    notifier = TelegramNotifier(bot_token, "12345", client=FailingClient())

    with pytest.raises(TelegramNotifierError, match="Telegram API request failed") as error:
        notifier.send_test_message()

    assert bot_token not in str(error.value)


def test_notifier_reports_invalid_telegram_api_responses() -> None:
    notifier = TelegramNotifier("test-token", "12345", client=InvalidResponseClient())

    with pytest.raises(TelegramNotifierError, match="invalid"):
        notifier.send_test_message()


def test_notifier_rejects_non_object_telegram_api_responses() -> None:
    notifier = TelegramNotifier("test-token", "12345", client=NonObjectResponseClient())

    with pytest.raises(TelegramNotifierError, match="invalid"):
        notifier.send_test_message()
