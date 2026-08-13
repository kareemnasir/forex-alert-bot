from datetime import UTC, datetime

import httpx
import pytest

from forex_alert_bot.news import (
    MARKETAUX_NEWS_URL,
    MarketauxNewsProvider,
    NewsError,
    NewsFetcher,
    NewsItem,
    create_news_provider,
    keywords_for_pairs,
)


class PayloadResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class StaticClient:
    def __init__(self, payload: object) -> None:
        self.response = PayloadResponse(payload)

    def get(self, *args: object, **kwargs: object) -> PayloadResponse:
        return self.response


class RecordingClient(StaticClient):
    def __init__(self, payload: object) -> None:
        super().__init__(payload)
        self.calls: list[tuple[str, dict[str, str | int], float]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        timeout: float,
    ) -> PayloadResponse:
        self.calls.append((url, params, timeout))
        return self.response


class UnavailableClient:
    def get(self, url: str, **kwargs: object) -> PayloadResponse:
        raise httpx.ConnectError("connection failed", request=httpx.Request("GET", url))


class ErrorStatusClient:
    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        timeout: float,
    ) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(401, request=request)


class StaticProvider:
    def __init__(self, items: list[NewsItem]) -> None:
        self.items = items

    def fetch_news(
        self,
        pairs: tuple[str, ...],
        *,
        published_after: datetime,
        limit: int,
    ) -> list[NewsItem]:
        return self.items


class FailingProvider:
    def fetch_news(
        self,
        pairs: tuple[str, ...],
        *,
        published_after: datetime,
        limit: int,
    ) -> list[NewsItem]:
        raise httpx.ConnectError("provider unavailable")


def test_pair_keywords_include_currencies_countries_and_central_banks() -> None:
    keywords = keywords_for_pairs(("EUR/USD", "GBP/USD", "USD/JPY"))

    assert "EUR" in keywords
    assert "eurozone" in keywords
    assert "ECB" in keywords
    assert "USD" in keywords
    assert "Federal Reserve" in keywords
    assert "GBP" in keywords
    assert "Bank of England" in keywords
    assert "JPY" in keywords
    assert "Bank of Japan" in keywords
    assert "inflation" in keywords
    assert "rates" in keywords


def test_marketaux_response_is_normalized_to_stable_news_items() -> None:
    provider = MarketauxNewsProvider(
        "test-api-key",
        client=StaticClient(
            {
                "meta": {"returned": 1},
                "data": [
                    {
                        "title": "ECB signals patience as eurozone inflation eases",
                        "source": "example.com",
                        "published_at": "2026-08-13T12:30:00.000000Z",
                        "url": "https://example.com/ecb-rates",
                        "description": "The central bank kept policy unchanged.",
                        "snippet": "Officials said future decisions remain data-dependent.",
                    }
                ],
            }
        ),
    )

    items = provider.fetch_news(
        ("EUR/USD",),
        published_after=datetime(2026, 8, 13, 6, tzinfo=UTC),
        limit=10,
    )

    assert items == [
        NewsItem(
            title="ECB signals patience as eurozone inflation eases",
            source="example.com",
            published_at=datetime(2026, 8, 13, 12, 30, tzinfo=UTC),
            url="https://example.com/ecb-rates",
            snippet="Officials said future decisions remain data-dependent.",
            related_pairs=(),
            related_currencies=(),
        )
    ]


def test_news_fetcher_adds_pair_and_currency_relevance_metadata() -> None:
    item = NewsItem(
        title="Bank of Japan keeps rates unchanged",
        source="example.com",
        published_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
        url=None,
        snippet="The yen rose after the BoJ statement.",
        related_pairs=(),
        related_currencies=(),
    )
    fetcher = NewsFetcher(StaticProvider([item]), max_age_hours=6, max_items=10)

    items = fetcher.fetch_recent(
        ("EUR/USD", "USD/JPY"),
        now=datetime(2026, 8, 13, 13, tzinfo=UTC),
    )

    assert items == [
        NewsItem(
            title=item.title,
            source=item.source,
            published_at=item.published_at,
            url=None,
            snippet=item.snippet,
            related_pairs=("USD/JPY",),
            related_currencies=("JPY",),
        )
    ]


def test_news_fetcher_filters_stale_articles() -> None:
    stale_item = NewsItem(
        title="Federal Reserve discusses rates",
        source="example.com",
        published_at=datetime(2026, 8, 13, 6, 59, tzinfo=UTC),
        url=None,
        snippet=None,
        related_pairs=(),
        related_currencies=(),
    )
    fetcher = NewsFetcher(StaticProvider([stale_item]), max_age_hours=6, max_items=10)

    assert (
        fetcher.fetch_recent(
            ("EUR/USD",),
            now=datetime(2026, 8, 13, 13, tzinfo=UTC),
        )
        == []
    )


def test_news_fetcher_filters_future_dated_articles() -> None:
    future_item = NewsItem(
        title="ECB announces a rate decision",
        source="example.com",
        published_at=datetime(2026, 8, 13, 13, 1, tzinfo=UTC),
        url=None,
        snippet=None,
        related_pairs=(),
        related_currencies=(),
    )
    fetcher = NewsFetcher(StaticProvider([future_item]), max_age_hours=6, max_items=10)

    assert (
        fetcher.fetch_recent(
            ("EUR/USD",),
            now=datetime(2026, 8, 13, 13, tzinfo=UTC),
        )
        == []
    )


def test_news_fetcher_filters_articles_without_configured_currency_context() -> None:
    irrelevant_item = NewsItem(
        title="Technology shares rise after earnings",
        source="example.com",
        published_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
        url=None,
        snippet="Investors focused on semiconductor demand.",
        related_pairs=(),
        related_currencies=(),
    )
    fetcher = NewsFetcher(StaticProvider([irrelevant_item]), max_age_hours=6, max_items=10)

    assert (
        fetcher.fetch_recent(
            ("EUR/USD",),
            now=datetime(2026, 8, 13, 13, tzinfo=UTC),
        )
        == []
    )


def test_empty_marketaux_response_returns_empty_list() -> None:
    provider = MarketauxNewsProvider(
        "test-api-key",
        client=StaticClient({"meta": {"returned": 0}, "data": []}),
    )

    assert (
        provider.fetch_news(
            ("EUR/USD",),
            published_after=datetime(2026, 8, 13, 6, tzinfo=UTC),
            limit=10,
        )
        == []
    )


def test_marketaux_provider_skips_malformed_articles() -> None:
    provider = MarketauxNewsProvider(
        "test-api-key",
        client=StaticClient(
            {
                "data": [
                    {"title": "missing required fields"},
                    {
                        "title": "Fed officials discuss inflation",
                        "source": "example.com",
                        "published_at": "2026-08-13T12:00:00Z",
                    },
                ]
            }
        ),
    )

    items = provider.fetch_news(
        ("EUR/USD",),
        published_after=datetime(2026, 8, 13, 6, tzinfo=UTC),
        limit=10,
    )

    assert [item.title for item in items] == ["Fed officials discuss inflation"]


def test_news_fetcher_degrades_gracefully_when_provider_fails() -> None:
    errors: list[Exception] = []
    fetcher = NewsFetcher(
        FailingProvider(),
        max_age_hours=6,
        max_items=10,
        error_handler=errors.append,
    )

    items = fetcher.fetch_recent(
        ("EUR/USD",),
        now=datetime(2026, 8, 13, 13, tzinfo=UTC),
    )

    assert items == []
    assert len(errors) == 1
    assert str(errors[0]) == "provider unavailable"


def test_marketaux_provider_factory_and_request_use_news_configuration() -> None:
    provider = create_news_provider("marketaux", "configured-news-key")
    assert isinstance(provider, MarketauxNewsProvider)

    client = RecordingClient({"data": []})
    provider = MarketauxNewsProvider(
        "configured-news-key",
        client=client,
        timeout_seconds=3.5,
    )

    provider.fetch_news(
        ("EUR/USD", "GBP/USD"),
        published_after=datetime(2026, 8, 13, 6, 15, tzinfo=UTC),
        limit=7,
    )

    assert len(client.calls) == 1
    url, params, timeout = client.calls[0]
    assert url == MARKETAUX_NEWS_URL
    assert params["api_token"] == "configured-news-key"
    assert params["language"] == "en"
    assert params["limit"] == 7
    assert params["published_after"] == "2026-08-13T06:15:00"
    assert "ECB" in str(params["search"])
    assert "Bank of England" in str(params["search"])
    assert timeout == 3.5


def test_marketaux_search_avoids_generic_macro_only_terms() -> None:
    client = RecordingClient({"data": []})
    provider = MarketauxNewsProvider("test-api-key", client=client)

    provider.fetch_news(
        ("EUR/USD",),
        published_after=datetime(2026, 8, 13, 6, tzinfo=UTC),
        limit=10,
    )

    search = str(client.calls[0][1]["search"])
    assert "EUR" in search
    assert "ECB" in search
    assert "Federal Reserve" in search
    assert "inflation" not in search
    assert "interest rates" not in search
    assert "rates" not in search


def test_news_fetcher_matches_unknown_configured_currency_code() -> None:
    item = NewsItem(
        title="MXN strengthens after central bank decision",
        source="example.com",
        published_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
        url=None,
        snippet=None,
        related_pairs=(),
        related_currencies=(),
    )
    fetcher = NewsFetcher(StaticProvider([item]), max_age_hours=6, max_items=10)

    assert fetcher.fetch_recent(
        ("MXN/JPY",),
        now=datetime(2026, 8, 13, 13, tzinfo=UTC),
    ) == [
        NewsItem(
            title=item.title,
            source=item.source,
            published_at=item.published_at,
            url=None,
            snippet=None,
            related_pairs=("MXN/JPY",),
            related_currencies=("MXN",),
        )
    ]


def test_news_fetcher_does_not_match_lowercase_us_or_fed_prose() -> None:
    items = [
        NewsItem(
            title="Company gives us its quarterly outlook",
            source="example.com",
            published_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
            url=None,
            snippet=None,
            related_pairs=(),
            related_currencies=(),
        ),
        NewsItem(
            title="Workers were fed before the meeting",
            source="example.com",
            published_at=datetime(2026, 8, 13, 12, 1, tzinfo=UTC),
            url=None,
            snippet=None,
            related_pairs=(),
            related_currencies=(),
        ),
    ]
    fetcher = NewsFetcher(StaticProvider(items), max_age_hours=6, max_items=10)

    assert (
        fetcher.fetch_recent(
            ("EUR/USD",),
            now=datetime(2026, 8, 13, 13, tzinfo=UTC),
        )
        == []
    )


def test_news_fetcher_matches_capitalized_us_and_fed_aliases() -> None:
    item = NewsItem(
        title="US Fed officials discuss policy",
        source="example.com",
        published_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
        url=None,
        snippet=None,
        related_pairs=(),
        related_currencies=(),
    )
    fetcher = NewsFetcher(StaticProvider([item]), max_age_hours=6, max_items=10)

    result = fetcher.fetch_recent(
        ("EUR/USD",),
        now=datetime(2026, 8, 13, 13, tzinfo=UTC),
    )

    assert result[0].related_currencies == ("USD",)


def test_news_fetcher_returns_newest_items_before_applying_limit() -> None:
    items = [
        NewsItem(
            title=f"USD item {hour}",
            source="example.com",
            published_at=datetime(2026, 8, 13, hour, tzinfo=UTC),
            url=None,
            snippet=None,
            related_pairs=(),
            related_currencies=(),
        )
        for hour in (10, 12, 11)
    ]
    fetcher = NewsFetcher(StaticProvider(items), max_age_hours=6, max_items=2)

    result = fetcher.fetch_recent(
        ("EUR/USD",),
        now=datetime(2026, 8, 13, 13, tzinfo=UTC),
    )

    assert [item.title for item in result] == ["USD item 12", "USD item 11"]


def test_marketaux_error_logging_does_not_expose_api_key(caplog: pytest.LogCaptureFixture) -> None:
    secret = "super-secret-news-key"
    provider = MarketauxNewsProvider(secret, client=ErrorStatusClient())

    def fail_to_record(error: Exception) -> None:
        raise RuntimeError("database unavailable")

    fetcher = NewsFetcher(
        provider,
        max_age_hours=6,
        max_items=10,
        error_handler=fail_to_record,
    )

    assert (
        fetcher.fetch_recent(
            ("EUR/USD",),
            now=datetime(2026, 8, 13, 13, tzinfo=UTC),
        )
        == []
    )
    assert secret not in caplog.text


def test_marketaux_provider_wraps_transport_failures() -> None:
    provider = MarketauxNewsProvider("test-api-key", client=UnavailableClient())

    with pytest.raises(NewsError, match="Marketaux request failed"):
        provider.fetch_news(
            ("EUR/USD",),
            published_after=datetime(2026, 8, 13, 6, tzinfo=UTC),
            limit=10,
        )
