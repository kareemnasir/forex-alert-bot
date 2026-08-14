import json
from datetime import UTC, datetime

import httpx
import pytest

from forex_alert_bot.config import Settings
from forex_alert_bot.news import NewsItem
from forex_alert_bot.sentiment import (
    NewsSentiment,
    NewsSentimentAnalyzer,
    OllamaCloudProvider,
    RiskLevel,
    SentimentDirection,
    SentimentProviderError,
    SentimentStatus,
    create_sentiment_analyzer,
)
from forex_alert_bot.strategies import CandidateSignal


class PayloadResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class RecordingHttpClient:
    def __init__(self, payload: object) -> None:
        self.response = PayloadResponse(payload)
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> PayloadResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


class ErrorStatusHttpClient:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(self.status_code, request=httpx.Request("POST", url))


class TransportErrorHttpClient:
    def post(self, url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("connection failed", request=request)


class RecordingProvider:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def news_item(
    title: str = "ECB signals patience as inflation eases",
    *,
    pair: str = "EUR/USD",
) -> NewsItem:
    return NewsItem(
        title=title,
        source="example.com",
        published_at=datetime(2026, 8, 13, 12, 30, tzinfo=UTC),
        url="https://example.com/article",
        snippet="Officials said future decisions remain data-dependent.",
        related_pairs=(pair,),
        related_currencies=tuple(pair.split("/")),
    )


def test_valid_provider_response_becomes_stable_sentiment_objects() -> None:
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "bullish",
                            "strength": 0.42,
                            "risk_level": "medium",
                            "summary": "Headlines mildly favor EUR over USD.",
                        }
                    ],
                    "major_news_risk": False,
                }
            )
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=1)

    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.AVAILABLE
    assert result.major_news_risk is False
    assert result.headline_count == 1
    assert result.attempts == 1
    assert len(result.pair_impacts) == 1
    impact = result.pair_impacts[0]
    assert impact.pair == "EUR/USD"
    assert impact.direction is SentimentDirection.BULLISH
    assert impact.strength == 0.42
    assert impact.risk_level is RiskLevel.MEDIUM
    assert impact.summary == "Headlines mildly favor EUR over USD."


def test_invalid_json_returns_unavailable_sentiment_safely() -> None:
    provider = RecordingProvider(["not JSON"])
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=0)

    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.UNAVAILABLE
    assert result.major_news_risk is None
    assert result.headline_count == 1
    assert result.attempts == 1
    assert result.raw_response == "not JSON"
    assert result.error == "Sentiment response was invalid."
    assert len(result.pair_impacts) == 1
    assert result.pair_impacts[0].pair == "EUR/USD"
    assert result.pair_impacts[0].direction is SentimentDirection.UNAVAILABLE
    assert result.pair_impacts[0].risk_level is RiskLevel.UNKNOWN
    assert result.pair_impacts[0].strength == 0.0


def test_invalid_json_is_retried_once_before_succeeding() -> None:
    provider = RecordingProvider(
        [
            "not JSON",
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "uncertain",
                            "strength": 0.15,
                            "risk_level": "low",
                            "summary": "Evidence is weak and mixed.",
                        }
                    ],
                    "major_news_risk": False,
                }
            ),
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=1)

    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.AVAILABLE
    assert result.attempts == 2
    assert len(provider.prompts) == 2


def test_api_error_returns_unavailable_sentiment_safely() -> None:
    provider = RecordingProvider(
        [SentimentProviderError("Ollama Cloud request failed", retryable=False)]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=1)

    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.UNAVAILABLE
    assert result.attempts == 1
    assert result.raw_response is None
    assert result.error == "Sentiment provider was unavailable."
    assert len(provider.prompts) == 1


def test_unexpected_provider_error_returns_unavailable_sentiment_safely() -> None:
    provider = RecordingProvider([RuntimeError("unexpected provider failure")])
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=1)

    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.UNAVAILABLE
    assert result.attempts == 1
    assert result.error == "Sentiment provider was unavailable."


def test_transient_api_error_is_retried_once_before_succeeding() -> None:
    provider = RecordingProvider(
        [
            SentimentProviderError("Ollama Cloud request failed", retryable=True),
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "neutral",
                            "strength": 0.2,
                            "risk_level": "low",
                            "summary": "The headlines are broadly balanced.",
                        }
                    ],
                    "major_news_risk": False,
                }
            ),
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=1)

    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.AVAILABLE
    assert result.attempts == 2
    assert len(provider.prompts) == 2


def test_prompt_contains_required_sentiment_guardrails() -> None:
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "neutral",
                            "strength": 0.1,
                            "risk_level": "low",
                            "summary": "Evidence is limited.",
                        }
                    ],
                    "major_news_risk": False,
                }
            )
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=0)

    analyzer.analyze([news_item()])

    prompt = provider.prompts[0].lower()
    assert "return json only" in prompt
    assert "analyze news sentiment, not trade entries" in prompt
    assert "do not recommend trades" in prompt
    assert "do not invent facts" in prompt
    assert "use only the provided headlines and articles" in prompt
    assert "if evidence is weak, use low strength" in prompt
    assert "mark uncertainty clearly" in prompt
    assert "keep summaries short" in prompt


def test_ollama_cloud_provider_uses_configured_key_host_model_and_timeout() -> None:
    content = '{"pair_impacts":[],"major_news_risk":false}'
    client = RecordingHttpClient(
        {"model": "glm-5.2-cloud", "message": {"role": "assistant", "content": content}}
    )
    provider = OllamaCloudProvider(
        api_key="ollama-cloud-token",
        host="https://custom.ollama.example/",
        model="glm-5.2-cloud",
        timeout_seconds=12.5,
        client=client,
    )

    result = provider.complete("sentiment prompt")

    assert result == content
    assert client.calls == [
        {
            "url": "https://custom.ollama.example/api/chat",
            "headers": {
                "Authorization": "Bearer ollama-cloud-token",
                "Content-Type": "application/json",
            },
            "json": {
                "model": "glm-5.2-cloud",
                "messages": [{"role": "user", "content": "sentiment prompt"}],
                "stream": False,
            },
            "timeout": 12.5,
        }
    ]


def test_ollama_cloud_provider_accepts_api_base_url_without_duplicating_path() -> None:
    content = '{"pair_impacts":[],"major_news_risk":false}'
    client = RecordingHttpClient({"message": {"content": content}})
    provider = OllamaCloudProvider(
        api_key="ollama-cloud-token",
        host="https://custom.ollama.example/api",
        model="cloud-model",
        timeout_seconds=10,
        client=client,
    )

    provider.complete("sentiment prompt")

    assert client.calls[0]["url"] == "https://custom.ollama.example/api/chat"


@pytest.mark.parametrize(
    "host",
    ["http://ollama.example", "https://", "https://ollama.example?target=other"],
)
def test_ollama_cloud_provider_rejects_unsafe_or_malformed_hosts(host: str) -> None:
    with pytest.raises(SentimentProviderError, match="OLLAMA_HOST"):
        OllamaCloudProvider(
            api_key="test-token",
            host=host,
            model="cloud-model",
            timeout_seconds=10,
        )


def test_missing_required_model_fields_return_unavailable_safely() -> None:
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "bullish",
                            "strength": 0.4,
                            "summary": "Missing risk level.",
                        }
                    ],
                    "major_news_risk": False,
                }
            )
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=0)

    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.UNAVAILABLE
    assert result.error == "Sentiment response was invalid."


@pytest.mark.parametrize(
    "response_pairs",
    [
        ("EUR/USD", "EUR/USD"),
        ("EUR/USD",),
        ("EUR/USD", "GBP/USD", "USD/JPY"),
    ],
)
def test_response_pair_contract_violations_return_unavailable(
    response_pairs: tuple[str, ...],
) -> None:
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": pair,
                            "direction": "neutral",
                            "strength": 0.1,
                            "risk_level": "low",
                            "summary": "Evidence is limited.",
                        }
                        for pair in response_pairs
                    ],
                    "major_news_risk": False,
                }
            )
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=0)

    result = analyzer.analyze(
        [news_item(pair="EUR/USD"), news_item(pair="GBP/USD")],
        pairs=("EUR/USD", "GBP/USD"),
    )

    assert result.status is SentimentStatus.UNAVAILABLE
    assert result.error == "Sentiment response was invalid."
    assert tuple(impact.pair for impact in result.pair_impacts) == ("EUR/USD", "GBP/USD")


def test_empty_news_does_not_call_provider_and_returns_cleanly() -> None:
    provider = RecordingProvider([])
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=1)

    result = analyzer.analyze([])

    assert result.status is SentimentStatus.NO_RELEVANT_NEWS
    assert result.pair_impacts == ()
    assert result.major_news_risk is False
    assert result.headline_count == 0
    assert result.attempts == 0
    assert provider.prompts == []


def test_only_news_relevant_to_requested_pairs_is_sent() -> None:
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "neutral",
                            "strength": 0.1,
                            "risk_level": "low",
                            "summary": "Evidence is limited.",
                        }
                    ],
                    "major_news_risk": False,
                }
            )
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=0)

    analyzer.analyze(
        [
            news_item("ECB discusses rates", pair="EUR/USD"),
            news_item("Bank of England discusses rates", pair="GBP/USD"),
        ],
        pairs=("EUR/USD",),
    )

    prompt = provider.prompts[0]
    assert "ECB discusses rates" in prompt
    assert "Bank of England discusses rates" not in prompt


def test_headline_count_sent_to_provider_is_bounded() -> None:
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "neutral",
                            "strength": 0.1,
                            "risk_level": "low",
                            "summary": "Evidence is limited.",
                        }
                    ],
                    "major_news_risk": False,
                }
            )
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=2, retry_count=0)

    result = analyzer.analyze(
        [
            news_item("First relevant headline"),
            news_item("Second relevant headline"),
            news_item("Third relevant headline"),
        ]
    )

    assert result.headline_count == 2
    assert "First relevant headline" in provider.prompts[0]
    assert "Second relevant headline" in provider.prompts[0]
    assert "Third relevant headline" not in provider.prompts[0]


def test_sentiment_module_does_not_create_trade_signals() -> None:
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "pair_impacts": [
                        {
                            "pair": "EUR/USD",
                            "direction": "bearish",
                            "strength": 0.7,
                            "risk_level": "high",
                            "summary": "Headlines favor USD over EUR.",
                        }
                    ],
                    "major_news_risk": True,
                }
            )
        ]
    )
    analyzer = NewsSentimentAnalyzer(provider=provider, max_headlines=10, retry_count=0)

    result = analyzer.analyze([news_item()])

    assert isinstance(result, NewsSentiment)
    assert not isinstance(result, CandidateSignal)
    assert result.pair_impacts[0].direction.value not in {"BUY", "SELL"}


def test_sentiment_factory_wires_ollama_settings_into_analyzer() -> None:
    content = json.dumps(
        {
            "pair_impacts": [
                {
                    "pair": "EUR/USD",
                    "direction": "neutral",
                    "strength": 0.1,
                    "risk_level": "low",
                    "summary": "Evidence is limited.",
                }
            ],
            "major_news_risk": False,
        }
    )
    client = RecordingHttpClient({"message": {"content": content}})
    settings = Settings.from_environment(
        {
            "OLLAMA_API_KEY": "factory-token",
            "OLLAMA_HOST": "https://factory.ollama.example",
            "OLLAMA_MODEL": "gpt-oss:120b-cloud",
            "OLLAMA_TIMEOUT_SECONDS": "9",
            "OLLAMA_MAX_HEADLINES": "4",
            "OLLAMA_RETRY_COUNT": "0",
        }
    )

    analyzer = create_sentiment_analyzer(settings, client=client)
    result = analyzer.analyze([news_item()])

    assert result.status is SentimentStatus.AVAILABLE
    assert client.calls[0]["url"] == "https://factory.ollama.example/api/chat"
    assert client.calls[0]["timeout"] == 9.0
    request_body = client.calls[0]["json"]
    assert isinstance(request_body, dict)
    assert request_body["model"] == "gpt-oss:120b-cloud"


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(400, False), (404, False), (429, True), (500, True), (502, True)],
)
def test_ollama_cloud_provider_classifies_http_failures(
    status_code: int,
    retryable: bool,
) -> None:
    provider = OllamaCloudProvider(
        api_key="test-token",
        host="https://ollama.example",
        model="cloud-model",
        timeout_seconds=10,
        client=ErrorStatusHttpClient(status_code),
    )

    with pytest.raises(SentimentProviderError) as captured:
        provider.complete("sentiment prompt")

    assert str(captured.value) == "Ollama Cloud request failed"
    assert captured.value.retryable is retryable


def test_ollama_cloud_provider_converts_transport_failure_to_retryable_error() -> None:
    provider = OllamaCloudProvider(
        api_key="test-token",
        host="https://ollama.example",
        model="cloud-model",
        timeout_seconds=10,
        client=TransportErrorHttpClient(),
    )

    with pytest.raises(SentimentProviderError) as captured:
        provider.complete("sentiment prompt")

    assert str(captured.value) == "Ollama Cloud request failed"
    assert captured.value.retryable is True


@pytest.mark.parametrize(
    "payload",
    [{"unexpected": "shape"}, {"message": {"content": "  "}}],
)
def test_ollama_cloud_provider_rejects_invalid_response_envelopes(payload: object) -> None:
    provider = OllamaCloudProvider(
        api_key="test-token",
        host="https://ollama.example",
        model="cloud-model",
        timeout_seconds=10,
        client=RecordingHttpClient(payload),
    )

    with pytest.raises(SentimentProviderError) as captured:
        provider.complete("sentiment prompt")

    assert str(captured.value) == "Ollama Cloud response was invalid"
    assert captured.value.retryable is True
