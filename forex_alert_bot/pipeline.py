"""End-to-end orchestration for one Forex signal check."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from forex_alert_bot.alert_formatting import format_alert_decision
from forex_alert_bot.config import Settings
from forex_alert_bot.cooldown import AlertCooldownService, CooldownPolicy
from forex_alert_bot.database import DecisionStage, DeliverySkipType, SQLiteLog
from forex_alert_bot.indicators import IndicatorSnapshot, calculate_indicator_snapshot
from forex_alert_bot.market_data import (
    Candle,
    MarketDataProvider,
    MarketDataRateLimitError,
    create_market_data_provider,
)
from forex_alert_bot.news import (
    NewsFetcher,
    NewsItem,
    NewsProvider,
    create_news_provider,
)
from forex_alert_bot.news_adjustment import NewsAdjustmentPolicy, ScoreAdjustment
from forex_alert_bot.scoring import AlertDecision, AlertLevel, score_candidate_signals
from forex_alert_bot.sentiment import (
    NewsSentiment,
    SentimentStatus,
    create_sentiment_analyzer,
)
from forex_alert_bot.strategies import (
    BREAKOUT_STRATEGY,
    MEAN_REVERSION_STRATEGY,
    TREND_PULLBACK_STRATEGY,
    CandidateSignal,
    evaluate_breakout,
    evaluate_mean_reversion,
    evaluate_trend_pullback,
)
from forex_alert_bot.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class SentimentAnalyzer(Protocol):
    """Sentiment operation used after candidate-scoped news retrieval."""

    def analyze(
        self,
        news_items: Sequence[NewsItem],
        pairs: Sequence[str] | None = None,
    ) -> NewsSentiment: ...


class AlertNotifier(Protocol):
    """Delivery boundary used only after formatting and cooldown checks."""

    def send_alert(self, message: str) -> None: ...


@dataclass(frozen=True)
class PipelineRunResult:
    """Inspectable outcome of one completed pipeline run."""

    run_id: int
    candidates: tuple[CandidateSignal, ...]
    technical_decisions: tuple[AlertDecision, ...]
    final_decisions: tuple[AlertDecision, ...]
    sent_alert_ids: tuple[int, ...]


@dataclass
class SignalPipeline:
    """Compose deterministic strategies, advisory news, and alert delivery."""

    settings: Settings
    database: SQLiteLog
    market_data_provider: MarketDataProvider | None = None
    news_provider: NewsProvider | None = None
    sentiment_analyzer: SentimentAnalyzer | None = None
    notifier: AlertNotifier | None = None
    news_adjustment_policy: NewsAdjustmentPolicy = NewsAdjustmentPolicy()
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def run(self) -> PipelineRunResult:
        """Run the complete decision flow and persist every observable outcome."""
        run_id = self.database.start_run(dry_run=self.settings.dry_run)
        try:
            candles = self._fetch_candles(run_id)
            indicators = {key: _indicator_history(series) for key, series in candles.items()}
            candidates = self._run_strategies(candles, indicators)
            candidate_ids = {
                candidate: self._record_candidate(run_id, candidate) for candidate in candidates
            }
            technical_decisions = score_candidate_signals(candidates)
            technical_records = [
                (
                    decision,
                    self._record_decision(
                        run_id,
                        stage=DecisionStage.TECHNICAL,
                        decision=decision,
                        candidate_ids=candidate_ids,
                        news_analysis_id=None,
                    ),
                )
                for decision in technical_decisions
            ]

            candidate_pairs = tuple(
                dict.fromkeys(
                    decision.pair
                    for decision in technical_decisions
                    if decision.pair is not None and decision.direction is not None
                )
            )
            news_items, sentiment = self._analyze_news(run_id, candidate_pairs)
            final_decisions: list[AlertDecision] = []
            sent_alert_ids: list[int] = []
            evaluated_at = self.clock()
            cooldown = AlertCooldownService(
                self.database,
                CooldownPolicy(self.settings.alert_cooldown_minutes),
            )
            notifier = self.notifier

            for technical_decision, technical_decision_id in technical_records:
                candidate_id = _primary_candidate_id(technical_decision, candidate_ids)
                news_analysis_id = self.database.record_news_analysis(
                    run_id,
                    candidate_signal_id=candidate_id,
                    input_payload=_news_input_payload(
                        technical_decision,
                        news_items,
                        candidate_pairs,
                    ),
                    output_payload=sentiment.model_dump(mode="json"),
                    status=sentiment.status.value,
                )
                adjustment = self.news_adjustment_policy.apply(
                    technical_decision,
                    sentiment,
                )
                final_decision = adjustment.final_decision
                final_decisions.append(final_decision)
                final_decision_id = self._record_decision(
                    run_id,
                    stage=DecisionStage.FINAL,
                    decision=final_decision,
                    candidate_ids=candidate_ids,
                    news_analysis_id=news_analysis_id,
                )
                self._record_adjustment(
                    run_id,
                    technical_decision_id=technical_decision_id,
                    final_decision_id=final_decision_id,
                    news_analysis_id=news_analysis_id,
                    adjustment=adjustment,
                )
                if final_decision.level is AlertLevel.NO_ALERT:
                    continue

                cooldown_result = cooldown.evaluate(
                    run_id,
                    final_decision,
                    evaluated_at=evaluated_at,
                )
                if not cooldown_result.allowed:
                    continue
                message = format_alert_decision(final_decision)
                if message is None:
                    self.database.record_alert_delivery_skip(
                        run_id,
                        alert_decision_id=final_decision_id,
                        skip_type=DeliverySkipType.FORMATTING,
                        reason="Qualifying decision did not produce an alert message.",
                        fingerprint=cooldown_result.fingerprint,
                    )
                    continue
                if self.settings.dry_run:
                    self.database.record_alert_delivery_skip(
                        run_id,
                        alert_decision_id=final_decision_id,
                        skip_type=DeliverySkipType.DRY_RUN,
                        reason="Dry run suppressed Telegram delivery.",
                        fingerprint=cooldown_result.fingerprint,
                        message=message,
                        skipped_at=evaluated_at,
                    )
                    continue
                if candidate_id is None:
                    self.database.record_alert_delivery_skip(
                        run_id,
                        alert_decision_id=final_decision_id,
                        skip_type=DeliverySkipType.DELIVERY_UNAVAILABLE,
                        reason="Telegram delivery was unavailable.",
                        fingerprint=cooldown_result.fingerprint,
                        message=message,
                        skipped_at=evaluated_at,
                    )
                    continue
                if notifier is None:
                    try:
                        notifier = TelegramNotifier(
                            self.settings.telegram_bot_token,
                            self.settings.telegram_chat_id,
                        )
                    except Exception as error:
                        self._record_error(run_id, stage="telegram", error=error)
                        self.database.record_alert_delivery_skip(
                            run_id,
                            alert_decision_id=final_decision_id,
                            skip_type=DeliverySkipType.DELIVERY_UNAVAILABLE,
                            reason="Telegram delivery was unavailable.",
                            fingerprint=cooldown_result.fingerprint,
                            message=message,
                            skipped_at=evaluated_at,
                        )
                        continue
                try:
                    notifier.send_alert(message)
                except Exception as error:
                    self._record_error(run_id, stage="telegram", error=error)
                    self.database.record_alert_delivery_skip(
                        run_id,
                        alert_decision_id=final_decision_id,
                        skip_type=DeliverySkipType.DELIVERY_ERROR,
                        reason="Telegram delivery failed.",
                        fingerprint=cooldown_result.fingerprint,
                        message=message,
                        skipped_at=evaluated_at,
                    )
                    continue
                sent_alert_ids.append(
                    self.database.record_alert(
                        run_id,
                        candidate_signal_id=candidate_id,
                        news_analysis_id=news_analysis_id,
                        message=message,
                        fingerprint=cooldown_result.fingerprint,
                        alert_decision_id=final_decision_id,
                        sent_at=evaluated_at,
                    )
                )

            self.database.complete_run(run_id)
            return PipelineRunResult(
                run_id=run_id,
                candidates=candidates,
                technical_decisions=technical_decisions,
                final_decisions=tuple(final_decisions),
                sent_alert_ids=tuple(sent_alert_ids),
            )
        except Exception as error:
            try:
                self.database.fail_run(run_id, stage="signal-check", error=error)
            except Exception:
                logger.exception("Unable to persist signal-pipeline failure.")
            raise

    def _fetch_candles(self, run_id: int) -> dict[tuple[str, str], tuple[Candle, ...]]:
        candles = {
            (pair, timeframe): ()
            for pair in self.settings.market_data_pairs
            for timeframe in self.settings.market_data_timeframes
        }
        provider = self.market_data_provider
        if provider is None:
            try:
                provider = create_market_data_provider(
                    self.settings.market_data_provider,
                    self.settings.market_data_api_key,
                )
            except Exception as error:
                self._record_error(run_id, stage="market-data", error=error)
                return candles
        for pair in self.settings.market_data_pairs:
            for timeframe in self.settings.market_data_timeframes:
                try:
                    candles[(pair, timeframe)] = tuple(provider.fetch_candles(pair, timeframe))
                except MarketDataRateLimitError as error:
                    self._record_error(run_id, stage="market-data", error=error)
                    return candles
                except Exception as error:
                    self._record_error(run_id, stage="market-data", error=error)
        return candles

    def _run_strategies(
        self,
        candles: dict[tuple[str, str], tuple[Candle, ...]],
        indicators: dict[tuple[str, str], tuple[IndicatorSnapshot, ...]],
    ) -> tuple[CandidateSignal, ...]:
        candidates: list[CandidateSignal] = []
        for pair in self.settings.market_data_pairs:
            for timeframe in self.settings.market_data_timeframes:
                key = (pair, timeframe)
                series = candles[key]
                snapshots = indicators[key]
                if not series or not snapshots:
                    continue
                if BREAKOUT_STRATEGY in self.settings.technical_strategies and (
                    candidate := evaluate_breakout(
                        pair=pair,
                        timeframe=timeframe,
                        candles=series,
                        latest_indicators=snapshots[-1],
                    )
                ):
                    candidates.append(candidate)
                if MEAN_REVERSION_STRATEGY in self.settings.technical_strategies and (
                    candidate := evaluate_mean_reversion(
                        pair=pair,
                        timeframe=timeframe,
                        candles=series,
                        indicators=snapshots,
                    )
                ):
                    candidates.append(candidate)

            if TREND_PULLBACK_STRATEGY not in self.settings.technical_strategies:
                continue
            higher_timeframe = _highest_timeframe(self.settings.market_data_timeframes)
            if higher_timeframe is None:
                continue
            higher_snapshots = indicators[(pair, higher_timeframe)]
            if not higher_snapshots:
                continue
            for timeframe in self.settings.market_data_timeframes:
                if timeframe == higher_timeframe:
                    continue
                key = (pair, timeframe)
                if candidate := evaluate_trend_pullback(
                    pair=pair,
                    timeframe=timeframe,
                    higher_indicators=higher_snapshots[-1],
                    lower_indicators=indicators[key],
                    lower_candles=candles[key],
                ):
                    candidates.append(candidate)
        return tuple(candidates)

    def _analyze_news(
        self,
        run_id: int,
        candidate_pairs: tuple[str, ...],
    ) -> tuple[tuple[NewsItem, ...], NewsSentiment]:
        if not candidate_pairs:
            return (), _no_relevant_news()
        provider = self.news_provider
        if provider is None:
            try:
                provider = create_news_provider(
                    self.settings.news_provider,
                    self.settings.news_api_key,
                )
            except Exception as error:
                self._record_error(run_id, stage="news", error=error)
                return (), _unavailable_news("News provider was unavailable.")
        fetch_error: Exception | None = None

        def record_fetch_error(error: Exception) -> None:
            nonlocal fetch_error
            fetch_error = error
            self._record_error(run_id, stage="news", error=error)

        news_items = tuple(
            NewsFetcher(
                provider=provider,
                max_age_hours=self.settings.news_max_age_hours,
                max_items=self.settings.news_max_items,
                error_handler=record_fetch_error,
            ).fetch_recent(candidate_pairs, now=self.clock())
        )
        if fetch_error is not None:
            return news_items, _unavailable_news("News provider was unavailable.")
        if not news_items:
            return news_items, _no_relevant_news()
        analyzer = self.sentiment_analyzer
        if analyzer is None:
            try:
                analyzer = create_sentiment_analyzer(self.settings)
            except Exception as error:
                self._record_error(run_id, stage="sentiment", error=error)
                return news_items, _unavailable_news("Sentiment provider was unavailable.")
        try:
            sentiment = analyzer.analyze(
                news_items,
                pairs=candidate_pairs,
            )
        except Exception as error:
            self._record_error(run_id, stage="sentiment", error=error)
            return news_items, _unavailable_news("Sentiment provider was unavailable.")
        if sentiment.status is SentimentStatus.UNAVAILABLE:
            self._record_error(
                run_id,
                stage="sentiment",
                error=RuntimeError(sentiment.error or "Sentiment provider was unavailable."),
            )
        return news_items, sentiment

    def _record_error(self, run_id: int, *, stage: str, error: Exception) -> None:
        try:
            self.database.record_error(run_id, stage=stage, error=error)
        except Exception:
            logger.exception("Unable to persist %s failure.", stage)

    def _record_candidate(self, run_id: int, candidate: CandidateSignal) -> int:
        return self.database.record_candidate_signal(
            run_id,
            strategy=candidate.strategy,
            pair=candidate.pair,
            direction=candidate.direction.value,
            timeframe=candidate.timeframe,
            payload=_candidate_payload(candidate),
        )

    def _record_decision(
        self,
        run_id: int,
        *,
        stage: DecisionStage,
        decision: AlertDecision,
        candidate_ids: dict[CandidateSignal, int],
        news_analysis_id: int | None,
    ) -> int:
        return self.database.record_alert_decision(
            run_id,
            stage=stage,
            pair=decision.pair,
            direction=decision.direction.value if decision.direction else None,
            timeframe=decision.timeframe,
            alert_level=decision.level.value,
            score=decision.final_score,
            news_analysis_id=news_analysis_id,
            payload={
                "candidate_ids": [
                    candidate_ids[candidate] for candidate in decision.metadata.candidates
                ],
                "contributing_strategies": decision.contributing_strategies,
                "reasons": decision.reasons,
                "metadata": {
                    "candidate_count": decision.metadata.candidate_count,
                    "supporting_candidate_count": (decision.metadata.supporting_candidate_count),
                    "opposing_candidate_count": decision.metadata.opposing_candidate_count,
                    "technical_score": decision.metadata.technical_score,
                    "agreement_bonus": decision.metadata.agreement_bonus,
                    "conflict_penalty": decision.metadata.conflict_penalty,
                    "suppressed": decision.metadata.suppressed,
                },
            },
        )

    def _record_adjustment(
        self,
        run_id: int,
        *,
        technical_decision_id: int,
        final_decision_id: int,
        news_analysis_id: int,
        adjustment: ScoreAdjustment,
    ) -> None:
        self.database.record_score_adjustment(
            run_id,
            technical_decision_id=technical_decision_id,
            final_decision_id=final_decision_id,
            news_analysis_id=news_analysis_id,
            technical_score=adjustment.technical_score,
            score_delta=adjustment.score_delta,
            final_score=adjustment.final_decision.final_score,
            reasons=adjustment.reasons,
        )


def _indicator_history(candles: Sequence[Candle]) -> tuple[IndicatorSnapshot, ...]:
    if not candles:
        return ()
    first_end = max(1, len(candles) - 1)
    return tuple(
        snapshot
        for end in range(first_end, len(candles) + 1)
        if (snapshot := calculate_indicator_snapshot(candles[:end])) is not None
    )


def _highest_timeframe(timeframes: Sequence[str]) -> str | None:
    if len(timeframes) < 2:
        return None
    durations = {
        "min": 1,
        "h": 60,
        "day": 1440,
        "week": 10080,
        "month": 43200,
    }

    def minutes(value: str) -> int:
        suffix = next(
            item for item in sorted(durations, key=len, reverse=True) if value.endswith(item)
        )
        return int(value.removesuffix(suffix)) * durations[suffix]

    return max(timeframes, key=minutes)


def _candidate_payload(candidate: CandidateSignal) -> dict[str, object]:
    metadata = asdict(candidate.metadata) if candidate.metadata is not None else None
    if metadata is not None:
        metadata["signal_timestamp"] = candidate.metadata.signal_timestamp.isoformat()
    return {
        "score": candidate.score,
        "reasons": candidate.reasons,
        "invalidation_level": candidate.invalidation_level,
        "metadata": metadata,
    }


def _primary_candidate_id(
    decision: AlertDecision,
    candidate_ids: dict[CandidateSignal, int],
) -> int | None:
    if not decision.metadata.candidates:
        return None
    supporting = (
        tuple(
            candidate
            for candidate in decision.metadata.candidates
            if candidate.direction is decision.direction
        )
        or decision.metadata.candidates
    )
    candidate = min(supporting, key=lambda item: (-item.score, item.strategy))
    return candidate_ids[candidate]


def _news_input_payload(
    decision: AlertDecision,
    news_items: Sequence[NewsItem],
    candidate_pairs: Sequence[str],
) -> dict[str, object]:
    return {
        "pair": decision.pair,
        "technical_direction": decision.direction.value if decision.direction else None,
        "requested_pairs": candidate_pairs,
        "articles": [
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at.isoformat(),
                "url": item.url,
                "snippet": item.snippet,
                "related_pairs": item.related_pairs,
                "related_currencies": item.related_currencies,
            }
            for item in news_items
        ],
    }


def _no_relevant_news() -> NewsSentiment:
    return NewsSentiment(
        status=SentimentStatus.NO_RELEVANT_NEWS,
        pair_impacts=(),
        major_news_risk=False,
        headline_count=0,
        attempts=0,
    )


def _unavailable_news(error: str) -> NewsSentiment:
    return NewsSentiment(
        status=SentimentStatus.UNAVAILABLE,
        pair_impacts=(),
        major_news_risk=None,
        headline_count=0,
        attempts=0,
        error=error,
    )
