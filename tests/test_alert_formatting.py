from copy import deepcopy
from dataclasses import replace

import pytest

from forex_alert_bot.alert_formatting import format_alert_decision
from forex_alert_bot.scoring import AlertDecision, AlertDecisionMetadata, AlertLevel
from forex_alert_bot.strategies import CandidateSignal, SignalDirection


def test_strong_watch_includes_the_manual_decision_context() -> None:
    message = format_alert_decision(
        _decision(
            level=AlertLevel.STRONG_WATCH,
            score=86,
            strategies=("trend-pullback", "breakout"),
            reasons=("1h trend is down.", "15m RSI rejected.", "Price broke range low."),
        )
    )

    assert message == (
        "EUR/USD SELL Strong Watch\n"
        "Timeframe: 15m\n"
        "Score: 86/100\n"
        "Strategies: Trend Pullback + Breakout\n"
        "Reasons: 1h trend is down.; 15m RSI rejected.; Price broke range low.\n"
        "Invalidation: above 1.0960\n"
        "Manual decision only."
    )


@pytest.mark.parametrize(
    ("level", "score", "expected"),
    [
        (
            AlertLevel.WATCH,
            70,
            "EUR/USD SELL Watch\n"
            "Timeframe: 15m\n"
            "Score: 70/100\n"
            "Strategies: Trend Pullback\n"
            "Reasons: Trend remains down.\n"
            "Invalidation: above 1.0960\n"
            "Manual decision only.",
        ),
        (
            AlertLevel.WEAK_WATCH,
            55,
            "EUR/USD SELL Weak Watch\n"
            "Timeframe: 15m\n"
            "Score: 55/100\n"
            "Strategies: Trend Pullback\n"
            "Reasons: Trend remains down.\n"
            "Invalidation: above 1.0960\n"
            "Manual decision only.",
        ),
    ],
)
def test_non_strong_watch_levels_format_cleanly(
    level: AlertLevel, score: int, expected: str
) -> None:
    message = format_alert_decision(_decision(level=level, score=score))

    assert message == expected


def test_no_alert_returns_no_message() -> None:
    assert format_alert_decision(_decision(level=AlertLevel.NO_ALERT, score=49)) is None


def test_missing_optional_fields_are_omitted_without_crashing() -> None:
    decision = replace(
        _decision(),
        pair=None,
        timeframe=None,
        direction=None,
        contributing_strategies=(),
        reasons=(),
        metadata=AlertDecisionMetadata(
            candidate_count=0,
            supporting_candidate_count=0,
            opposing_candidate_count=0,
            technical_score=0,
            agreement_bonus=0,
            conflict_penalty=0,
            suppressed=False,
            candidates=(),
        ),
    )

    message = format_alert_decision(decision)

    assert message == "Watch\nScore: 70/100\nManual decision only."


def test_message_sanitizes_aggressive_phrases_from_reasons() -> None:
    message = format_alert_decision(
        _decision(
            strategies=("guaranteed-profit",),
            reasons=("BUY NOW for guaranteed profit.",),
        )
    )

    assert message is not None
    assert "BUY NOW" not in message.upper()
    assert "GUARANTEED" not in message.upper()
    assert "PROFIT" not in message.upper()


def test_long_reasons_are_truncated_cleanly() -> None:
    message = format_alert_decision(_decision(reasons=("a" * 200,)))

    assert message is not None
    assert "Reasons: " + ("a" * 157) + "..." in message
    assert len(message) < 500


def test_formatting_does_not_mutate_the_decision() -> None:
    decision = _decision()
    original = deepcopy(decision)

    format_alert_decision(decision)

    assert decision == original


def test_buy_invalidation_uses_the_highest_scoring_supporting_candidate() -> None:
    decision = _decision(direction=SignalDirection.BUY, score=80)
    lower_scoring_candidate = replace(
        decision.metadata.candidates[0],
        score=70,
        invalidation_level=1.08,
    )
    decision = replace(
        decision,
        metadata=replace(
            decision.metadata,
            candidates=(lower_scoring_candidate, decision.metadata.candidates[0]),
        ),
    )

    message = format_alert_decision(decision)

    assert message is not None
    assert "Invalidation: below 1.0960" in message


def _decision(
    *,
    level: AlertLevel = AlertLevel.WATCH,
    score: int = 70,
    strategies: tuple[str, ...] = ("trend-pullback",),
    reasons: tuple[str, ...] = ("Trend remains down.",),
    direction: SignalDirection = SignalDirection.SELL,
) -> AlertDecision:
    return AlertDecision(
        pair="EUR/USD",
        timeframe="15m",
        direction=direction,
        level=level,
        final_score=score,
        contributing_strategies=strategies,
        reasons=reasons,
        metadata=AlertDecisionMetadata(
            candidate_count=1,
            supporting_candidate_count=1,
            opposing_candidate_count=0,
            technical_score=score,
            agreement_bonus=0,
            conflict_penalty=0,
            suppressed=False,
            candidates=(
                CandidateSignal(
                    pair="EUR/USD",
                    timeframe="15m",
                    strategy="trend-pullback",
                    direction=direction,
                    score=score,
                    reasons=("Trend remains down.",),
                    invalidation_level=1.096,
                ),
            ),
        ),
    )
