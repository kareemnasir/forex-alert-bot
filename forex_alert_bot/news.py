"""Provider-neutral retrieval and normalization of relevant Forex news."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

MARKETAUX_NEWS_URL = "https://api.marketaux.com/v1/news/all"
DEFAULT_NEWS_TIMEOUT_SECONDS = 10.0

logger = logging.getLogger(__name__)


class NewsError(RuntimeError):
    """Base error for a recoverable news-fetch failure."""


class NewsConfigurationError(NewsError):
    """Raised when news settings cannot make a valid request."""


class NewsResponseError(NewsError):
    """Raised when a provider response cannot be normalized."""


@dataclass(frozen=True)
class NewsItem:
    """One normalized article ready for later sentiment analysis."""

    title: str
    source: str
    published_at: datetime
    url: str | None
    snippet: str | None
    related_pairs: tuple[str, ...]
    related_currencies: tuple[str, ...]


class NewsHttpClient(Protocol):
    """The small subset of an HTTP client used by news providers."""

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        timeout: float,
    ) -> httpx.Response: ...


class NewsProvider(Protocol):
    """The stable provider boundary used by the news fetcher."""

    def fetch_news(
        self,
        pairs: Sequence[str],
        *,
        published_after: datetime,
        limit: int,
    ) -> list[NewsItem]: ...


@dataclass(frozen=True)
class NewsFetcher:
    """Fetch, filter, and enrich recent news for configured Forex pairs."""

    provider: NewsProvider
    max_age_hours: int
    max_items: int
    error_handler: Callable[[Exception], None] | None = None

    def __post_init__(self) -> None:
        if self.max_age_hours <= 0:
            raise NewsConfigurationError("News maximum age must be positive")
        if self.max_items <= 0:
            raise NewsConfigurationError("News item limit must be positive")

    def fetch_recent(
        self,
        pairs: Sequence[str],
        *,
        now: datetime | None = None,
    ) -> list[NewsItem]:
        """Return newest-first relevant items without exposing provider details."""
        fetched_at = datetime.now(UTC) if now is None else now
        if fetched_at.utcoffset() is None:
            raise NewsConfigurationError("now must include timezone information")
        fetched_at = fetched_at.astimezone(UTC)
        cutoff = fetched_at - timedelta(hours=self.max_age_hours)
        try:
            items = self.provider.fetch_news(pairs, published_after=cutoff, limit=self.max_items)
        except Exception as error:
            logger.warning("News fetch failed: %s", error)
            if self.error_handler is not None:
                try:
                    self.error_handler(error)
                except Exception:
                    logger.exception("Unable to record news-fetch failure.")
            return []
        relevant_items = [
            enriched
            for item in items
            if cutoff <= item.published_at <= fetched_at
            if (enriched := _add_relevance(item, pairs)) is not None
        ]
        return sorted(
            relevant_items,
            key=lambda item: (item.published_at, item.title, item.source, item.url or ""),
            reverse=True,
        )[: self.max_items]


class MarketauxNewsProvider:
    """Fetch and normalize articles from Marketaux behind the news boundary."""

    def __init__(
        self,
        api_key: str | None,
        *,
        client: NewsHttpClient | None = None,
        timeout_seconds: float = DEFAULT_NEWS_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key:
            raise NewsConfigurationError("NEWS_API_KEY must be configured")
        if timeout_seconds <= 0:
            raise NewsConfigurationError("News timeout must be positive")
        self._api_key = api_key
        self._client = client or httpx
        self._timeout_seconds = timeout_seconds

    def fetch_news(
        self,
        pairs: Sequence[str],
        *,
        published_after: datetime,
        limit: int,
    ) -> list[NewsItem]:
        """Return normalized articles for all configured pairs in one request."""
        if published_after.utcoffset() is None:
            raise NewsConfigurationError("published_after must include timezone information")
        if limit <= 0:
            raise NewsConfigurationError("News item limit must be positive")
        try:
            response = self._client.get(
                MARKETAUX_NEWS_URL,
                params={
                    "api_token": self._api_key,
                    "search": _marketaux_search_query(_currency_keywords_for_pairs(pairs)),
                    "language": "en",
                    "limit": limit,
                    "published_after": published_after.astimezone(UTC).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise NewsError("Marketaux request failed") from None
        try:
            payload = response.json()
        except ValueError as error:
            raise NewsResponseError("Marketaux returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise NewsResponseError("Marketaux returned an invalid response")
        items: list[NewsItem] = []
        for item in payload["data"]:
            try:
                items.append(_normalize_marketaux_item(item))
            except NewsResponseError as error:
                logger.warning("Skipped malformed Marketaux article: %s", error)
        return items


def create_news_provider(provider_name: str, api_key: str | None) -> NewsProvider:
    """Build the configured news provider without coupling callers to Marketaux."""
    if provider_name == "marketaux":
        return MarketauxNewsProvider(api_key)
    raise NewsConfigurationError(f"Unsupported news provider: {provider_name}")


_CURRENCY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "AUD": ("AUD", "Australian dollar", "Australia", "Reserve Bank of Australia", "RBA"),
    "CAD": ("CAD", "Canadian dollar", "Canada", "Bank of Canada", "BoC"),
    "CHF": ("CHF", "Swiss franc", "Switzerland", "Swiss National Bank", "SNB"),
    "EUR": ("EUR", "euro", "eurozone", "European Central Bank", "ECB"),
    "GBP": ("GBP", "pound sterling", "sterling", "UK", "Bank of England", "BoE"),
    "JPY": ("JPY", "yen", "Japan", "Bank of Japan", "BoJ"),
    "NZD": ("NZD", "New Zealand dollar", "New Zealand", "Reserve Bank of New Zealand", "RBNZ"),
    "USD": ("USD", "US dollar", "US", "United States", "Federal Reserve", "Fed"),
}
_MACRO_KEYWORDS = ("inflation", "interest rates", "rates")
_CASE_SENSITIVE_TERMS = frozenset({"US", "Fed"})


def _currency_keywords_for_pairs(pairs: Sequence[str]) -> tuple[str, ...]:
    keywords: list[str] = []
    for pair in pairs:
        currencies = pair.strip().upper().split("/")
        for currency in currencies:
            keywords.extend(_CURRENCY_KEYWORDS.get(currency, (currency,)))
    return tuple(dict.fromkeys(keywords))


def keywords_for_pairs(pairs: Sequence[str]) -> tuple[str, ...]:
    """Return a stable, de-duplicated relevance vocabulary for configured pairs."""
    return (*_currency_keywords_for_pairs(pairs), *_MACRO_KEYWORDS)


def _marketaux_search_query(keywords: Sequence[str]) -> str:
    return "|".join(f'"{keyword}"' if " " in keyword else keyword for keyword in keywords)


def _add_relevance(item: NewsItem, pairs: Sequence[str]) -> NewsItem | None:
    searchable_text = " ".join(part for part in (item.title, item.snippet) if part)
    configured_currencies = tuple(
        dict.fromkeys(currency for pair in pairs for currency in pair.strip().upper().split("/"))
    )
    related_currencies = tuple(
        currency
        for currency in configured_currencies
        if any(
            _contains_term(searchable_text, term)
            for term in _CURRENCY_KEYWORDS.get(currency, (currency,))
        )
    )
    if not related_currencies:
        return None
    related_pairs = tuple(
        pair.strip().upper()
        for pair in pairs
        if any(currency in related_currencies for currency in pair.strip().upper().split("/"))
    )
    return replace(
        item,
        related_pairs=related_pairs,
        related_currencies=related_currencies,
    )


def _contains_term(text: str, term: str) -> bool:
    flags = 0 if term in _CASE_SENSITIVE_TERMS else re.IGNORECASE
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=flags) is not None


def _normalize_marketaux_item(value: object) -> NewsItem:
    if not isinstance(value, dict):
        raise NewsResponseError("Marketaux returned a malformed article")
    title = _required_text(value.get("title"), field="title")
    source = _required_text(value.get("source"), field="source")
    published_at = _parse_marketaux_timestamp(value.get("published_at"))
    return NewsItem(
        title=title,
        source=source,
        published_at=published_at,
        url=_optional_text(value.get("url")),
        snippet=_optional_text(value.get("snippet")) or _optional_text(value.get("description")),
        related_pairs=(),
        related_currencies=(),
    )


def _required_text(value: object, *, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise NewsResponseError(f"Marketaux article {field} is invalid")
    return text


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _parse_marketaux_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise NewsResponseError("Marketaux article published_at is invalid")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise NewsResponseError("Marketaux article published_at is invalid") from error
    if timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
