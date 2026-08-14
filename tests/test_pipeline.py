import math
from datetime import UTC, datetime, timedelta

from forex_alert_bot.config import Settings
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.market_data import Candle, MarketDataRateLimitError
from forex_alert_bot.news import NewsItem
from forex_alert_bot.pipeline import SignalPipeline
from forex_alert_bot.sentiment import (
    NewsSentiment,
    PairNewsImpact,
    RiskLevel,
    SentimentDirection,
    SentimentStatus,
)


class BreakoutMarketDataProvider:
    def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
        started_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
        candles = [
            Candle(
                timestamp=started_at + timedelta(minutes=15 * index),
                open=1.0,
                high=1.01,
                low=0.99,
                close=1.0,
                volume=None,
            )
            for index in range(20)
        ]
        candles.append(
            Candle(
                timestamp=started_at + timedelta(minutes=15 * 20),
                open=1.0,
                high=1.015,
                low=0.995,
                close=1.012,
                volume=None,
            )
        )
        return candles


class RelevantNewsProvider:
    def fetch_news(self, pairs, *, published_after, limit):
        return [
            NewsItem(
                title="ECB policy outlook supports the euro",
                source="example.com",
                published_at=datetime(2026, 8, 14, 15, 0, tzinfo=UTC),
                url="https://example.com/ecb",
                snippet="ECB officials discussed the EUR outlook.",
                related_pairs=(),
                related_currencies=(),
            )
        ]


class ConflictingMarketDataProvider:
    def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
        started_at = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
        closes = [1 + (0.05 * math.sin(2 * math.pi * index / 20)) for index in range(40)]
        candles = []
        for index, close in enumerate(closes):
            open_price = closes[index - 1] if index else close
            candles.append(
                Candle(
                    timestamp=started_at + timedelta(minutes=15 * index),
                    open=open_price,
                    high=max(open_price, close) + 0.003,
                    low=min(open_price, close) - 0.003,
                    close=close,
                    volume=None,
                )
            )
        range_high = max(candle.high for candle in candles[-20:])
        candles.append(
            Candle(
                timestamp=started_at + timedelta(minutes=15 * 40),
                open=range_high - 0.025,
                high=range_high + 0.008,
                low=range_high - 0.03,
                close=range_high + 0.002,
                volume=None,
            )
        )
        return candles


class AgreeingMarketDataProvider:
    def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
        started_at = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
        if timeframe == "1h":
            closes = [1 + (0.0003 * index) for index in range(220)]
            step = timedelta(hours=1)
        else:
            closes = [1 + (0.0001 * index) for index in range(220)]
            closes.extend(closes[-1] - (0.0005 * step) for step in range(1, 4))
            step = timedelta(minutes=15)

        candles = []
        for index, close in enumerate(closes):
            open_price = closes[index - 1] if index else close
            candles.append(
                Candle(
                    timestamp=started_at + (step * index),
                    open=open_price,
                    high=max(open_price, close) + 0.0005,
                    low=min(open_price, close) - 0.0005,
                    close=close,
                    volume=None,
                )
            )
        if timeframe == "15min":
            range_high = max(candle.high for candle in candles[-20:])
            open_price = candles[-1].close
            close = range_high + 0.0005
            candles.append(
                Candle(
                    timestamp=started_at + (step * len(candles)),
                    open=open_price,
                    high=close + 0.0005,
                    low=open_price - 0.0005,
                    close=close,
                    volume=None,
                )
            )
        return candles


class SupportingSentimentAnalyzer:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def analyze(self, news_items, pairs=None) -> NewsSentiment:
        self.calls.append(
            (
                tuple(item.title for item in news_items),
                tuple(pairs or ()),
            )
        )
        return NewsSentiment(
            status=SentimentStatus.AVAILABLE,
            pair_impacts=(
                PairNewsImpact(
                    pair="EUR/USD",
                    direction=SentimentDirection.BULLISH,
                    strength=0.6,
                    risk_level=RiskLevel.LOW,
                    summary="News modestly supports EUR over USD.",
                ),
            ),
            major_news_risk=False,
            headline_count=1,
            attempts=1,
        )


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_alert(self, message: str) -> None:
        self.messages.append(message)


def test_qualifying_candidate_records_complete_dry_run_flow_without_sending(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    sentiment = SupportingSentimentAnalyzer()
    notifier = RecordingNotifier()
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=True,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=BreakoutMarketDataProvider(),
        news_provider=RelevantNewsProvider(),
        sentiment_analyzer=sentiment,
        notifier=notifier,
        clock=lambda: datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
    )

    result = pipeline.run()

    assert database.get_run(result.run_id)["status"] == "completed"
    assert [candidate.strategy for candidate in result.candidates] == ["breakout"]
    assert result.final_decisions[0].final_score == 74
    assert result.final_decisions[0].direction.value == "BUY"
    assert sentiment.calls == [(("ECB policy outlook supports the euro",), ("EUR/USD",))]
    assert notifier.messages == []
    flow = database.get_decision_flow(result.run_id)
    assert [decision["stage"] for decision in flow["decisions"]] == [
        "technical",
        "final",
    ]
    assert flow["adjustments"][0]["score_delta"] == 6
    assert flow["candidates"][0]["strategy"] == "breakout"
    assert flow["news_analyses"][0]["status"] == "available"
    assert flow["news_analyses"][0]["input"]["requested_pairs"] == ["EUR/USD"]
    assert flow["news_analyses"][0]["output"]["pair_impacts"][0]["pair"] == ("EUR/USD")
    assert flow["delivery_skips"][0]["skip_type"] == "dry_run"
    assert "EUR/USD BUY Watch" in flow["delivery_skips"][0]["message"]
    assert "News supports BUY" in flow["delivery_skips"][0]["message"]


def test_market_data_provider_failure_records_error_without_crashing(tmp_path) -> None:
    class FailingMarketDataProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
            raise MarketDataRateLimitError("API credits exhausted")

    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    pipeline = SignalPipeline(
        settings=Settings(
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=FailingMarketDataProvider(),
    )

    result = pipeline.run()

    assert database.get_run(result.run_id)["status"] == "completed"
    assert database.get_errors(result.run_id) == [
        {
            "run_id": result.run_id,
            "stage": "market-data",
            "error_type": "MarketDataRateLimitError",
            "message": "API credits exhausted",
        }
    ]
    assert result.candidates == ()
    assert result.final_decisions[0].level.value == "No Alert"


def test_market_data_failure_stays_recoverable_when_error_logging_fails(tmp_path) -> None:
    class ErrorWriteFailingLog(SQLiteLog):
        def record_error(self, run_id, *, stage, error, occurred_at=None):
            raise RuntimeError("database temporarily locked")

    class FailingMarketDataProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
            raise RuntimeError("provider unavailable")

    database = ErrorWriteFailingLog(tmp_path / "forex-alert-bot.sqlite3")
    pipeline = SignalPipeline(
        settings=Settings(
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=FailingMarketDataProvider(),
    )

    result = pipeline.run()

    assert database.get_run(result.run_id)["status"] == "completed"
    assert result.final_decisions[0].level.value == "No Alert"


def test_market_data_configuration_failure_starts_and_completes_run(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    pipeline = SignalPipeline(
        settings=Settings(
            database_path=database.path,
            market_data_api_key=None,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
    )

    result = pipeline.run()

    assert database.get_run(result.run_id)["status"] == "completed"
    assert database.get_errors(result.run_id)[0]["stage"] == "market-data"
    assert database.get_errors(result.run_id)[0]["error_type"] == ("MarketDataConfigurationError")


def test_news_provider_failure_records_error_and_skips_ollama(tmp_path) -> None:
    class FailingNewsProvider:
        def fetch_news(self, pairs, *, published_after, limit):
            raise RuntimeError("Marketaux unavailable")

    class UnexpectedSentimentAnalyzer:
        def analyze(self, news_items, pairs=None):
            raise AssertionError("Ollama must not run without relevant news")

    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=True,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=BreakoutMarketDataProvider(),
        news_provider=FailingNewsProvider(),
        sentiment_analyzer=UnexpectedSentimentAnalyzer(),
        clock=lambda: datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
    )

    result = pipeline.run()

    assert database.get_run(result.run_id)["status"] == "completed"
    assert database.get_errors(result.run_id) == [
        {
            "run_id": result.run_id,
            "stage": "news",
            "error_type": "RuntimeError",
            "message": "Marketaux unavailable",
        }
    ]
    assert result.final_decisions[0].final_score == 68
    flow = database.get_decision_flow(result.run_id)
    assert flow["news_analyses"][0]["status"] == "unavailable"
    assert "unavailable" in flow["adjustments"][0]["reasons"][0].lower()


def test_ollama_failure_records_unavailable_sentiment_without_crashing(tmp_path) -> None:
    class UnavailableSentimentAnalyzer:
        def analyze(self, news_items, pairs=None) -> NewsSentiment:
            return NewsSentiment(
                status=SentimentStatus.UNAVAILABLE,
                pair_impacts=(),
                major_news_risk=None,
                headline_count=1,
                attempts=1,
                error="Sentiment provider was unavailable.",
            )

    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=True,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=BreakoutMarketDataProvider(),
        news_provider=RelevantNewsProvider(),
        sentiment_analyzer=UnavailableSentimentAnalyzer(),
        clock=lambda: datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
    )

    result = pipeline.run()

    assert database.get_run(result.run_id)["status"] == "completed"
    assert database.get_errors(result.run_id) == [
        {
            "run_id": result.run_id,
            "stage": "sentiment",
            "error_type": "RuntimeError",
            "message": "Sentiment provider was unavailable.",
        }
    ]
    assert result.final_decisions[0].final_score == 68
    assert any("unavailable" in reason.lower() for reason in result.final_decisions[0].reasons)


def test_news_and_ollama_cannot_create_alert_without_technical_candidates(tmp_path) -> None:
    class EmptyMarketDataProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
            return []

    class UnexpectedNewsProvider:
        def fetch_news(self, pairs, *, published_after, limit):
            raise AssertionError("News must not run without technical candidates")

    class UnexpectedSentimentAnalyzer:
        def analyze(self, news_items, pairs=None):
            raise AssertionError("Ollama must not run without technical candidates")

    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    notifier = RecordingNotifier()
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=False,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=EmptyMarketDataProvider(),
        news_provider=UnexpectedNewsProvider(),
        sentiment_analyzer=UnexpectedSentimentAnalyzer(),
        notifier=notifier,
    )

    result = pipeline.run()

    assert result.candidates == ()
    assert result.final_decisions[0].level.value == "No Alert"
    assert result.sent_alert_ids == ()
    assert notifier.messages == []
    assert database.get_errors(result.run_id) == []


def test_supported_monthly_timeframe_does_not_crash_strategy_selection(tmp_path) -> None:
    class EmptyMarketDataProvider:
        def fetch_candles(self, pair: str, timeframe: str) -> list[Candle]:
            return []

    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    pipeline = SignalPipeline(
        settings=Settings(
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("1h", "1month"),
            technical_strategies=("trend-pullback",),
        ),
        database=database,
        market_data_provider=EmptyMarketDataProvider(),
    )

    result = pipeline.run()

    assert database.get_run(result.run_id)["status"] == "completed"
    assert result.candidates == ()


def test_live_mode_sends_only_qualifying_alert_and_preserves_trace(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    notifier = RecordingNotifier()
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=False,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=BreakoutMarketDataProvider(),
        news_provider=RelevantNewsProvider(),
        sentiment_analyzer=SupportingSentimentAnalyzer(),
        notifier=notifier,
        clock=lambda: datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
    )

    result = pipeline.run()

    assert len(notifier.messages) == 1
    assert "EUR/USD BUY Watch" in notifier.messages[0]
    assert len(result.sent_alert_ids) == 1
    trace = database.get_alert_trace(result.sent_alert_ids[0])
    assert trace["alert_decision"]["stage"] == "final"
    assert trace["alert_decision"]["score"] == 74
    assert trace["score_adjustment"]["score_delta"] == 6


def test_live_mode_records_telegram_failure_without_sending_alert(tmp_path) -> None:
    class FailingNotifier:
        def send_alert(self, message: str) -> None:
            raise RuntimeError("Telegram unavailable")

    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=False,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=BreakoutMarketDataProvider(),
        news_provider=RelevantNewsProvider(),
        sentiment_analyzer=SupportingSentimentAnalyzer(),
        notifier=FailingNotifier(),
        clock=lambda: datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
    )

    result = pipeline.run()

    assert result.sent_alert_ids == ()
    assert database.get_run(result.run_id)["status"] == "completed"
    assert database.get_errors(result.run_id)[0]["stage"] == "telegram"
    skips = database.get_decision_flow(result.run_id)["delivery_skips"]
    assert skips[0]["skip_type"] == "delivery_error"
    assert skips[0]["message"].startswith("EUR/USD BUY Watch")


def test_multi_pair_trace_persists_the_exact_analyzer_call_input(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    sentiment = SupportingSentimentAnalyzer()
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=True,
            database_path=database.path,
            market_data_pairs=("EUR/USD", "GBP/USD"),
            market_data_timeframes=("15min",),
        ),
        database=database,
        market_data_provider=BreakoutMarketDataProvider(),
        news_provider=RelevantNewsProvider(),
        sentiment_analyzer=sentiment,
        clock=lambda: datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
    )

    result = pipeline.run()

    assert sentiment.calls == [(("ECB policy outlook supports the euro",), ("EUR/USD", "GBP/USD"))]
    inputs = [item["input"] for item in database.get_decision_flow(result.run_id)["news_analyses"]]
    assert len(inputs) == 2
    assert all(item["requested_pairs"] == ["EUR/USD", "GBP/USD"] for item in inputs)
    assert all(
        [article["title"] for article in item["articles"]]
        == ["ECB policy outlook supports the euro"]
        for item in inputs
    )


def test_cooldown_prevents_second_send_and_records_skip(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    notifier = RecordingNotifier()

    def pipeline_at(evaluated_at: datetime) -> SignalPipeline:
        return SignalPipeline(
            settings=Settings(
                dry_run=False,
                database_path=database.path,
                market_data_pairs=("EUR/USD",),
                market_data_timeframes=("15min",),
                alert_cooldown_minutes=120,
            ),
            database=database,
            market_data_provider=BreakoutMarketDataProvider(),
            news_provider=RelevantNewsProvider(),
            sentiment_analyzer=SupportingSentimentAnalyzer(),
            notifier=notifier,
            clock=lambda: evaluated_at,
        )

    first = pipeline_at(datetime(2026, 8, 14, 16, 0, tzinfo=UTC)).run()
    second = pipeline_at(datetime(2026, 8, 14, 16, 30, tzinfo=UTC)).run()

    assert len(first.sent_alert_ids) == 1
    assert second.sent_alert_ids == ()
    assert len(notifier.messages) == 1
    skips = database.get_alert_skips(second.run_id)
    assert len(skips) == 1
    assert skips[0]["matching_alert_id"] == first.sent_alert_ids[0]
    assert "cooldown" in skips[0]["reason"]


def test_opposing_strategy_candidates_flow_through_scorer_and_do_not_send(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    notifier = RecordingNotifier()
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=False,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min",),
            technical_strategies=("breakout", "mean-reversion"),
        ),
        database=database,
        market_data_provider=ConflictingMarketDataProvider(),
        notifier=notifier,
    )

    result = pipeline.run()

    assert {candidate.strategy for candidate in result.candidates} == {
        "breakout",
        "mean-reversion",
    }
    assert {candidate.direction.value for candidate in result.candidates} == {
        "BUY",
        "SELL",
    }
    assert result.technical_decisions[0].level.value == "No Alert"
    assert result.final_decisions[0].level.value == "No Alert"
    assert notifier.messages == []
    assert result.sent_alert_ids == ()


def test_same_direction_strategy_agreement_flows_into_final_decision(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    notifier = RecordingNotifier()
    pipeline = SignalPipeline(
        settings=Settings(
            dry_run=False,
            database_path=database.path,
            market_data_pairs=("EUR/USD",),
            market_data_timeframes=("15min", "1h"),
            technical_strategies=("breakout", "trend-pullback"),
        ),
        database=database,
        market_data_provider=AgreeingMarketDataProvider(),
        notifier=notifier,
        clock=lambda: datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
    )

    result = pipeline.run()

    decision = next(item for item in result.final_decisions if item.timeframe == "15min")
    assert decision.contributing_strategies == ("breakout", "trend-pullback")
    assert decision.final_score == 80
    assert decision.level.value == "Strong Watch"
    assert any("agreement added 10 points" in reason for reason in decision.reasons)
    assert len(notifier.messages) == 1
