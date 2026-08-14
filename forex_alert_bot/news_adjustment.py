"""Deterministic news adjustments for existing technical alert decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from forex_alert_bot.scoring import (
    AlertDecision,
    AlertLevel,
    SignalScorerConfig,
    level_for_score,
)
from forex_alert_bot.sentiment import (
    NewsSentiment,
    RiskLevel,
    SentimentDirection,
    SentimentStatus,
)
from forex_alert_bot.strategies import SignalDirection


@dataclass(frozen=True)
class NewsAdjustmentConfig:
    """Centralized score bounds for advisory news effects."""

    maximum_support_boost: int = 10
    maximum_contradiction_penalty: int = 20
    strong_contradiction_threshold: float = 0.75
    high_risk_penalty: int = 15
    suppress_major_news_risk: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_support_boost, bool)
            or not isinstance(self.maximum_support_boost, int)
            or self.maximum_support_boost < 0
        ):
            raise ValueError("maximum_support_boost must be a nonnegative integer")
        if (
            isinstance(self.maximum_contradiction_penalty, bool)
            or not isinstance(self.maximum_contradiction_penalty, int)
            or self.maximum_contradiction_penalty < 0
        ):
            raise ValueError("maximum_contradiction_penalty must be a nonnegative integer")
        if (
            not math.isfinite(self.strong_contradiction_threshold)
            or not 0 <= self.strong_contradiction_threshold <= 1
        ):
            raise ValueError("strong_contradiction_threshold must be from 0 to 1")
        if (
            isinstance(self.high_risk_penalty, bool)
            or not isinstance(self.high_risk_penalty, int)
            or self.high_risk_penalty < 0
        ):
            raise ValueError("high_risk_penalty must be a nonnegative integer")
        if not isinstance(self.suppress_major_news_risk, bool):
            raise ValueError("suppress_major_news_risk must be a boolean")


@dataclass(frozen=True)
class ScoreAdjustment:
    """An inspectable deterministic change to an existing alert decision."""

    technical_score: int
    score_delta: int
    reasons: tuple[str, ...]
    final_decision: AlertDecision


@dataclass(frozen=True)
class NewsAdjustmentPolicy:
    """Apply validated news sentiment without creating a trade direction."""

    config: NewsAdjustmentConfig = NewsAdjustmentConfig()
    scorer_config: SignalScorerConfig = SignalScorerConfig()

    def apply(
        self,
        decision: AlertDecision,
        sentiment: NewsSentiment,
    ) -> ScoreAdjustment:
        """Return a news-adjusted copy of an existing technical decision."""
        if (
            decision.level is AlertLevel.NO_ALERT
            or decision.pair is None
            or decision.direction is None
        ):
            reasons = ("News cannot create an alert from a rejected technical decision.",)
            return ScoreAdjustment(
                technical_score=decision.final_score,
                score_delta=0,
                reasons=reasons,
                final_decision=replace(
                    decision,
                    reasons=(*decision.reasons, *reasons),
                ),
            )
        impact = next(
            (item for item in sentiment.pair_impacts if item.pair == decision.pair),
            None,
        )
        supports_direction = impact is not None and (
            (
                decision.direction is SignalDirection.BUY
                and impact.direction is SentimentDirection.BULLISH
            )
            or (
                decision.direction is SignalDirection.SELL
                and impact.direction is SentimentDirection.BEARISH
            )
        )
        contradicts_direction = impact is not None and (
            (
                decision.direction is SignalDirection.BUY
                and impact.direction is SentimentDirection.BEARISH
            )
            or (
                decision.direction is SignalDirection.SELL
                and impact.direction is SentimentDirection.BULLISH
            )
        )
        if supports_direction and impact is not None:
            score_delta = round(impact.strength * self.config.maximum_support_boost)
            reasons = (
                f"News supports {decision.direction.value}; score increased by "
                f"{score_delta} points: {impact.summary}",
            )
        elif contradicts_direction and impact is not None:
            score_delta = -round(impact.strength * self.config.maximum_contradiction_penalty)
            reasons = (
                f"News contradicts {decision.direction.value}; score reduced by "
                f"{abs(score_delta)} points: {impact.summary}",
            )
        else:
            score_delta = 0
            if sentiment.status is SentimentStatus.UNAVAILABLE:
                reasons = ("News sentiment was unavailable; technical score was unchanged.",)
            elif sentiment.status is SentimentStatus.NO_RELEVANT_NEWS:
                reasons = ("No relevant news was available; technical score was unchanged.",)
            else:
                reasons = ("News was uncertain or neutral; technical score was unchanged.",)
        strong_contradiction = (
            contradicts_direction
            and impact is not None
            and impact.strength >= self.config.strong_contradiction_threshold
        )
        if strong_contradiction:
            reasons = (*reasons, "Strong contradiction suppressed the alert decision.")
        high_risk = impact is not None and impact.risk_level is RiskLevel.HIGH
        if high_risk:
            score_delta -= self.config.high_risk_penalty
            reasons = (
                *reasons,
                f"High news risk reduced the score by {self.config.high_risk_penalty} points.",
            )
        major_risk_suppression = (
            high_risk and sentiment.major_news_risk is True and self.config.suppress_major_news_risk
        )
        if major_risk_suppression:
            reasons = (*reasons, "Major news risk suppressed the alert decision.")
        final_score = max(0, min(100, decision.final_score + score_delta))
        final_level = (
            AlertLevel.NO_ALERT
            if strong_contradiction or major_risk_suppression
            else level_for_score(final_score, self.scorer_config)
        )
        final_decision = replace(
            decision,
            final_score=final_score,
            level=final_level,
            reasons=(*reasons, *decision.reasons),
            metadata=replace(
                decision.metadata,
                suppressed=final_level is AlertLevel.NO_ALERT,
            ),
        )
        return ScoreAdjustment(
            technical_score=decision.final_score,
            score_delta=final_score - decision.final_score,
            reasons=reasons,
            final_decision=final_decision,
        )
