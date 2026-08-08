"""Provider-neutral Forex candle retrieval and normalization."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

TWELVE_DATA_TIME_SERIES_URL = "https://api.twelvedata.com/time_series"
DEFAULT_CANDLE_LIMIT = 200
DEFAULT_TIMEOUT_SECONDS = 10.0


class MarketDataError(RuntimeError):
    """Base error for a safe-to-handle market-data fetch failure."""


class MarketDataConfigurationError(MarketDataError):
    """Raised when market-data settings cannot make a valid request."""


class MarketDataRateLimitError(MarketDataError):
    """Raised when the provider asks the client to slow down."""


class MarketDataResponseError(MarketDataError):
    """Raised when the provider response is missing or cannot be normalized."""


@dataclass(frozen=True)
class Candle:
    """One normalized OHLCV-like Forex candle in UTC."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


class MarketDataProvider(Protocol):
    """The stable boundary used by the scheduler and future providers."""

    def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
        """Return normalized candles for one pair and timeframe."""


class MarketDataHttpClient(Protocol):
    """The small subset of an HTTP client used by the Twelve Data provider."""

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response: ...


class TwelveDataProvider:
    """Fetch Forex candles from Twelve Data's REST time-series endpoint."""

    def __init__(
        self,
        api_key: str | None,
        *,
        client: MarketDataHttpClient | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = 1,
    ) -> None:
        if not api_key:
            raise MarketDataConfigurationError("MARKET_DATA_API_KEY must be configured")
        if timeout_seconds <= 0:
            raise MarketDataConfigurationError("Market-data timeout must be positive")
        if retries < 0:
            raise MarketDataConfigurationError("Market-data retries cannot be negative")

        self._api_key = api_key
        self._client = client or httpx
        self._timeout_seconds = timeout_seconds
        self._retries = retries

    def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
        """Fetch and normalize a compact, UTC Forex candle series."""
        response = self._request(pair, timeframe)
        payload = self._json_payload(response)
        self._raise_provider_error(payload)

        values = payload.get("values")
        if not isinstance(values, list) or not values:
            raise MarketDataResponseError("Twelve Data returned no candle data")

        source_timezone = _source_timezone(payload, timeframe)
        candles = [_normalize_candle(value, source_timezone, timeframe) for value in values]
        return sorted(candles, key=lambda candle: candle.timestamp)

    def _request(self, pair: str, timeframe: str) -> httpx.Response:
        params = {
            "symbol": pair,
            "interval": timeframe,
            "outputsize": DEFAULT_CANDLE_LIMIT,
            "timezone": "UTC",
        }
        headers = {"Authorization": f"apikey {self._api_key}"}

        for attempt in range(self._retries + 1):
            try:
                response = self._client.get(
                    TWELVE_DATA_TIME_SERIES_URL,
                    params=params,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 429:
                    raise MarketDataRateLimitError("Twelve Data rate limit reached") from error
                if error.response.status_code < 500 or attempt == self._retries:
                    raise MarketDataError("Twelve Data request failed") from error
            except httpx.TransportError as error:
                if attempt == self._retries:
                    raise MarketDataError("Twelve Data request failed") from error

            time.sleep(0.25)

        raise AssertionError("The request retry loop must return or raise")

    @staticmethod
    def _json_payload(response: httpx.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError as error:
            raise MarketDataResponseError("Twelve Data returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise MarketDataResponseError("Twelve Data returned an invalid response")
        return payload

    @staticmethod
    def _raise_provider_error(payload: dict[str, object]) -> None:
        if payload.get("status") != "error":
            return

        message = payload.get("message")
        error_message = message if isinstance(message, str) else "Twelve Data rejected the request"
        if str(payload.get("code")) == "429":
            raise MarketDataRateLimitError(error_message)
        raise MarketDataError(error_message)


def create_market_data_provider(provider_name: str, api_key: str | None) -> MarketDataProvider:
    """Build the configured provider without coupling callers to its implementation."""
    if provider_name == "twelve_data":
        return TwelveDataProvider(api_key)
    raise MarketDataConfigurationError(f"Unsupported market-data provider: {provider_name}")


def _source_timezone(payload: dict[str, object], timeframe: str) -> ZoneInfo:
    if timeframe not in {"1day", "1week", "1month"}:
        return ZoneInfo("UTC")

    meta = payload.get("meta")
    exchange_timezone = meta.get("exchange_timezone") if isinstance(meta, dict) else None
    if not isinstance(exchange_timezone, str):
        raise MarketDataResponseError("Twelve Data daily candle timezone is unavailable")
    try:
        return ZoneInfo(exchange_timezone)
    except ZoneInfoNotFoundError as error:
        raise MarketDataResponseError("Twelve Data daily candle timezone is invalid") from error


def _normalize_candle(value: object, source_timezone: ZoneInfo, timeframe: str) -> Candle:
    if not isinstance(value, dict):
        raise MarketDataResponseError("Twelve Data returned malformed candle data")

    timestamp = _parse_timestamp(value.get("datetime"), source_timezone, timeframe)
    open_price = _parse_number(value.get("open"), field="open")
    high = _parse_number(value.get("high"), field="high")
    low = _parse_number(value.get("low"), field="low")
    close = _parse_number(value.get("close"), field="close")
    volume = (
        _parse_number(value["volume"], field="volume") if value.get("volume") is not None else None
    )
    if not low <= open_price <= high or not low <= close <= high:
        raise MarketDataResponseError("Twelve Data candle OHLC values are invalid")

    return Candle(timestamp, open_price, high, low, close, volume)


def _parse_timestamp(value: object, source_timezone: ZoneInfo, timeframe: str) -> datetime:
    if not isinstance(value, str):
        raise MarketDataResponseError("Twelve Data candle timestamp is invalid")
    if timeframe not in {"1day", "1week", "1month"} and "T" not in value and " " not in value:
        raise MarketDataResponseError("Twelve Data intraday candle timestamp is invalid")

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MarketDataResponseError("Twelve Data candle timestamp is invalid") from error
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=source_timezone)
    return timestamp.astimezone(UTC)


def _parse_number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise MarketDataResponseError(f"Twelve Data candle {field} is invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise MarketDataResponseError(f"Twelve Data candle {field} is invalid") from error
    if not math.isfinite(number):
        raise MarketDataResponseError(f"Twelve Data candle {field} is invalid")
    return number
