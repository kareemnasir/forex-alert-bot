from datetime import UTC, datetime

import httpx
import pytest

from forex_alert_bot import market_data
from forex_alert_bot.market_data import (
    Candle,
    MarketDataError,
    MarketDataRateLimitError,
    MarketDataResponseError,
    TwelveDataProvider,
    create_market_data_provider,
)


class SuccessfulResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "meta": {"exchange_timezone": "America/New_York"},
            "status": "ok",
            "values": [
                {
                    "datetime": "2026-08-06 14:30:00",
                    "open": "1.0900",
                    "high": "1.0920",
                    "low": "1.0890",
                    "close": "1.0910",
                }
            ],
        }


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str | int], dict[str, str], float]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout: float,
    ) -> SuccessfulResponse:
        self.calls.append((url, params, headers, timeout))
        return SuccessfulResponse()


class StaticClient:
    def __init__(self, response: SuccessfulResponse) -> None:
        self.response = response

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout: float,
    ) -> SuccessfulResponse:
        return self.response


class PayloadResponse(SuccessfulResponse):
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def json(self) -> object:
        return self.payload


class HttpRateLimitedClient:
    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout: float,
    ) -> SuccessfulResponse:
        request = httpx.Request("GET", url)
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)


class FlakyServerClient:
    def __init__(self) -> None:
        self.calls = 0

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout: float,
    ) -> SuccessfulResponse:
        self.calls += 1
        if self.calls == 1:
            request = httpx.Request("GET", url)
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError("server error", request=request, response=response)
        return SuccessfulResponse()


class UnavailableClient:
    def __init__(self) -> None:
        self.calls = 0

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout: float,
    ) -> SuccessfulResponse:
        self.calls += 1
        raise httpx.ConnectError("connection failed", request=httpx.Request("GET", url))


def test_market_data_provider_factory_uses_configured_twelve_data_provider() -> None:
    provider = create_market_data_provider("twelve_data", "test-api-key")

    assert isinstance(provider, TwelveDataProvider)


def test_twelve_data_provider_normalizes_forex_candles_to_utc() -> None:
    client = RecordingClient()
    provider = TwelveDataProvider("test-api-key", client=client)

    candles = provider.fetch_candles("EUR/USD", "15min")

    assert candles == [
        Candle(
            timestamp=datetime(2026, 8, 6, 14, 30, tzinfo=UTC),
            open=1.09,
            high=1.092,
            low=1.089,
            close=1.091,
            volume=None,
        )
    ]


def test_twelve_data_provider_retries_one_transient_server_failure(monkeypatch) -> None:
    client = FlakyServerClient()
    delays: list[float] = []
    monkeypatch.setattr(market_data.time, "sleep", delays.append)
    provider = TwelveDataProvider("test-api-key", client=client)

    candles = provider.fetch_candles("EUR/USD", "15min")

    assert len(candles) == 1
    assert client.calls == 2
    assert delays == [0.25]


def test_twelve_data_provider_stops_after_its_transport_retry_budget(monkeypatch) -> None:
    client = UnavailableClient()
    monkeypatch.setattr(market_data.time, "sleep", lambda _: None)
    provider = TwelveDataProvider("test-api-key", client=client, retries=1)

    with pytest.raises(MarketDataError, match="request failed"):
        provider.fetch_candles("EUR/USD", "15min")

    assert client.calls == 2


def test_twelve_data_provider_rejects_malformed_candle_values() -> None:
    provider = TwelveDataProvider(
        "test-api-key",
        client=StaticClient(
            PayloadResponse(
                {
                    "status": "ok",
                    "values": [
                        {
                            "datetime": "2026-08-06 14:30:00",
                            "open": True,
                            "high": "1.0920",
                            "low": "1.0890",
                            "close": "1.0910",
                        }
                    ],
                }
            )
        ),
    )

    with pytest.raises(MarketDataResponseError, match="open"):
        provider.fetch_candles("EUR/USD", "15min")


def test_twelve_data_provider_rejects_missing_candles() -> None:
    provider = TwelveDataProvider(
        "test-api-key", client=StaticClient(PayloadResponse({"status": "ok", "values": []}))
    )

    with pytest.raises(MarketDataResponseError, match="no candle"):
        provider.fetch_candles("EUR/USD", "15min")


def test_twelve_data_provider_converts_offset_timestamps_to_utc() -> None:
    provider = TwelveDataProvider(
        "test-api-key",
        client=StaticClient(
            PayloadResponse(
                {
                    "status": "ok",
                    "values": [
                        {
                            "datetime": "2026-08-06T16:30:00+02:00",
                            "open": "1.0900",
                            "high": "1.0920",
                            "low": "1.0890",
                            "close": "1.0910",
                            "volume": "42",
                        }
                    ],
                }
            )
        ),
    )

    candle = provider.fetch_candles("EUR/USD", "15min")[0]

    assert candle.timestamp == datetime(2026, 8, 6, 14, 30, tzinfo=UTC)
    assert candle.volume == 42.0


def test_twelve_data_provider_uses_exchange_timezone_for_daily_candles() -> None:
    provider = TwelveDataProvider(
        "test-api-key",
        client=StaticClient(
            PayloadResponse(
                {
                    "meta": {"exchange_timezone": "America/New_York"},
                    "status": "ok",
                    "values": [
                        {
                            "datetime": "2026-08-06",
                            "open": "1.0900",
                            "high": "1.0920",
                            "low": "1.0890",
                            "close": "1.0910",
                        }
                    ],
                }
            )
        ),
    )

    candle = provider.fetch_candles("EUR/USD", "1day")[0]

    assert candle.timestamp == datetime(2026, 8, 6, 4, 0, tzinfo=UTC)


def test_twelve_data_provider_reports_rate_limit_payloads() -> None:
    provider = TwelveDataProvider(
        "test-api-key",
        client=StaticClient(
            PayloadResponse({"status": "error", "code": 429, "message": "API credits exhausted"})
        ),
    )

    with pytest.raises(MarketDataRateLimitError, match="credits exhausted"):
        provider.fetch_candles("EUR/USD", "15min")


def test_twelve_data_provider_recognizes_string_rate_limit_codes() -> None:
    provider = TwelveDataProvider(
        "test-api-key",
        client=StaticClient(
            PayloadResponse({"status": "error", "code": "429", "message": "API credits exhausted"})
        ),
    )

    with pytest.raises(MarketDataRateLimitError, match="credits exhausted"):
        provider.fetch_candles("EUR/USD", "15min")


def test_twelve_data_provider_reports_http_rate_limits_without_retrying() -> None:
    provider = TwelveDataProvider("test-api-key", client=HttpRateLimitedClient())

    with pytest.raises(MarketDataRateLimitError, match="rate limit"):
        provider.fetch_candles("EUR/USD", "15min")


def test_twelve_data_provider_reports_provider_error_payloads() -> None:
    provider = TwelveDataProvider(
        "test-api-key",
        client=StaticClient(
            PayloadResponse({"status": "error", "code": 401, "message": "Invalid API key"})
        ),
    )

    with pytest.raises(MarketDataError, match="Invalid API key"):
        provider.fetch_candles("EUR/USD", "15min")


@pytest.mark.parametrize(
    "candle",
    [
        {
            "datetime": "2026-08-06",
            "open": "1.0900",
            "high": "1.0920",
            "low": "1.0890",
            "close": "1.0910",
        },
        {
            "datetime": "2026-08-06 14:30:00",
            "open": "1.0900",
            "high": "1.0890",
            "low": "1.0920",
            "close": "1.0910",
        },
    ],
)
def test_twelve_data_provider_rejects_semantically_invalid_intraday_candles(
    candle: dict[str, str],
) -> None:
    provider = TwelveDataProvider(
        "test-api-key", client=StaticClient(PayloadResponse({"status": "ok", "values": [candle]}))
    )

    with pytest.raises(MarketDataResponseError):
        provider.fetch_candles("EUR/USD", "15min")
