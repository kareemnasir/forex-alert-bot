from forex_alert_bot.news_adjustment import NewsAdjustmentConfig, NewsAdjustmentPolicy
from forex_alert_bot.scoring import score_candidate_signals
from forex_alert_bot.sentiment import (
    NewsSentiment,
    PairNewsImpact,
    RiskLevel,
    SentimentDirection,
    SentimentStatus,
)
from forex_alert_bot.strategies import CandidateSignal, SignalDirection


def test_supporting_news_boosts_an_existing_technical_decision() -> None:
    technical_decision = score_candidate_signals(
        [
            CandidateSignal(
                pair="EUR/USD",
                timeframe="15min",
                strategy="breakout",
                direction=SignalDirection.BUY,
                score=65,
                reasons=("Range breakout confirmed.",),
                invalidation_level=1.09,
            )
        ]
    )[0]
    sentiment = NewsSentiment(
        status=SentimentStatus.AVAILABLE,
        pair_impacts=(
            PairNewsImpact(
                pair="EUR/USD",
                direction=SentimentDirection.BULLISH,
                strength=0.6,
                risk_level=RiskLevel.LOW,
                summary="Headlines modestly favor EUR over USD.",
            ),
        ),
        major_news_risk=False,
        headline_count=1,
        attempts=1,
    )

    adjustment = NewsAdjustmentPolicy().apply(technical_decision, sentiment)

    assert adjustment.technical_score == 65
    assert adjustment.score_delta == 6
    assert adjustment.final_decision.final_score == 71
    assert adjustment.final_decision.direction is SignalDirection.BUY
    assert any("News supports BUY" in reason for reason in adjustment.reasons)


def test_contradicting_news_reduces_an_existing_technical_decision() -> None:
    technical_decision = score_candidate_signals(
        [
            CandidateSignal(
                pair="EUR/USD",
                timeframe="15min",
                strategy="trend-pullback",
                direction=SignalDirection.BUY,
                score=70,
                reasons=("Trend pullback confirmed.",),
                invalidation_level=1.09,
            )
        ]
    )[0]
    sentiment = NewsSentiment(
        status=SentimentStatus.AVAILABLE,
        pair_impacts=(
            PairNewsImpact(
                pair="EUR/USD",
                direction=SentimentDirection.BEARISH,
                strength=0.5,
                risk_level=RiskLevel.MEDIUM,
                summary="Headlines modestly favor USD over EUR.",
            ),
        ),
        major_news_risk=False,
        headline_count=1,
        attempts=1,
    )

    adjustment = NewsAdjustmentPolicy().apply(technical_decision, sentiment)

    assert adjustment.score_delta == -10
    assert adjustment.final_decision.final_score == 60
    assert adjustment.final_decision.direction is SignalDirection.BUY
    assert any("News contradicts BUY" in reason for reason in adjustment.reasons)


def test_strong_contradiction_suppresses_an_existing_decision() -> None:
    technical_decision = _technical_decision(score=80)
    sentiment = _sentiment(
        direction=SentimentDirection.BEARISH,
        strength=0.8,
        risk_level=RiskLevel.MEDIUM,
    )

    adjustment = NewsAdjustmentPolicy().apply(technical_decision, sentiment)

    assert adjustment.score_delta == -16
    assert adjustment.final_decision.final_score == 64
    assert adjustment.final_decision.level.value == "No Alert"
    assert adjustment.final_decision.metadata.suppressed is True
    assert any("strong contradiction" in reason.lower() for reason in adjustment.reasons)


def test_unavailable_sentiment_keeps_technical_decision_and_adds_reason() -> None:
    technical_decision = _technical_decision(score=70)
    sentiment = NewsSentiment(
        status=SentimentStatus.UNAVAILABLE,
        pair_impacts=(),
        major_news_risk=None,
        headline_count=1,
        attempts=1,
        error="Sentiment provider was unavailable.",
    )

    adjustment = NewsAdjustmentPolicy().apply(technical_decision, sentiment)

    assert adjustment.score_delta == 0
    assert adjustment.final_decision.final_score == 70
    assert adjustment.final_decision.level == technical_decision.level
    assert any("unavailable" in reason.lower() for reason in adjustment.reasons)


def test_major_high_risk_news_reduces_and_suppresses_existing_decision() -> None:
    technical_decision = _technical_decision(score=80)
    sentiment = _sentiment(
        direction=SentimentDirection.BULLISH,
        strength=0.6,
        risk_level=RiskLevel.HIGH,
    ).model_copy(update={"major_news_risk": True})

    adjustment = NewsAdjustmentPolicy().apply(technical_decision, sentiment)

    assert adjustment.score_delta == -9
    assert adjustment.final_decision.final_score == 71
    assert adjustment.final_decision.level.value == "No Alert"
    assert any("major news risk" in reason.lower() for reason in adjustment.reasons)


def test_news_cannot_turn_no_alert_into_trade_alert() -> None:
    technical_decision = _technical_decision(score=49)
    sentiment = _sentiment(
        direction=SentimentDirection.BULLISH,
        strength=1.0,
        risk_level=RiskLevel.LOW,
    )

    adjustment = NewsAdjustmentPolicy().apply(technical_decision, sentiment)

    assert adjustment.score_delta == 0
    assert adjustment.final_decision.final_score == 49
    assert adjustment.final_decision.level.value == "No Alert"
    assert any("cannot create" in reason.lower() for reason in adjustment.reasons)


def test_supporting_news_clamps_final_score_to_one_hundred() -> None:
    technical_decision = _technical_decision(score=100)
    sentiment = _sentiment(
        direction=SentimentDirection.BULLISH,
        strength=1.0,
        risk_level=RiskLevel.LOW,
    )

    adjustment = NewsAdjustmentPolicy().apply(technical_decision, sentiment)

    assert adjustment.final_decision.final_score == 100
    assert adjustment.score_delta == 0


def test_news_penalties_clamp_final_score_to_zero() -> None:
    technical_decision = _technical_decision(score=50)
    sentiment = _sentiment(
        direction=SentimentDirection.BEARISH,
        strength=0.9,
        risk_level=RiskLevel.HIGH,
    )
    policy = NewsAdjustmentPolicy(
        config=NewsAdjustmentConfig(
            maximum_contradiction_penalty=100,
            strong_contradiction_threshold=1.0,
            high_risk_penalty=100,
            suppress_major_news_risk=False,
        )
    )

    adjustment = policy.apply(technical_decision, sentiment)

    assert adjustment.final_decision.final_score == 0
    assert adjustment.score_delta == -50


def _technical_decision(*, score: int = 70):
    return score_candidate_signals(
        [
            CandidateSignal(
                pair="EUR/USD",
                timeframe="15min",
                strategy="breakout",
                direction=SignalDirection.BUY,
                score=score,
                reasons=("Range breakout confirmed.",),
                invalidation_level=1.09,
            )
        ]
    )[0]


def _sentiment(
    *,
    direction: SentimentDirection,
    strength: float,
    risk_level: RiskLevel,
) -> NewsSentiment:
    return NewsSentiment(
        status=SentimentStatus.AVAILABLE,
        pair_impacts=(
            PairNewsImpact(
                pair="EUR/USD",
                direction=direction,
                strength=strength,
                risk_level=risk_level,
                summary="Relevant headlines were analyzed.",
            ),
        ),
        major_news_risk=False,
        headline_count=1,
        attempts=1,
    )
