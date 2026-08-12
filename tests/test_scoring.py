from datetime import UTC, datetime

import pytest

from forex_alert_bot.scoring import (
    AlertLevel,
    SignalScorerConfig,
    score_candidate_signals,
)
from forex_alert_bot.strategies import (
    CandidateSignal,
    CandidateSignalMetadata,
    SignalDirection,
)


def test_empty_candidates_returns_no_alert() -> None:
    decisions = score_candidate_signals([])

    assert len(decisions) == 1
    assert decisions[0].level is AlertLevel.NO_ALERT
    assert decisions[0].pair is None
    assert decisions[0].timeframe is None
    assert decisions[0].direction is None


def test_one_strong_candidate_returns_strong_watch() -> None:
    decisions = score_candidate_signals([_candidate(score=80)])

    assert len(decisions) == 1
    assert decisions[0].level is AlertLevel.STRONG_WATCH
    assert decisions[0].final_score == 80


def test_weak_candidate_below_threshold_returns_no_alert() -> None:
    decision = score_candidate_signals([_candidate(score=49)])[0]

    assert decision.level is AlertLevel.NO_ALERT
    assert decision.final_score == 49


def test_same_direction_candidates_get_agreement_boost() -> None:
    decision = score_candidate_signals(
        [
            _candidate(strategy="trend-pullback", score=70),
            _candidate(strategy="breakout", score=68),
        ]
    )[0]

    assert decision.final_score == 80
    assert decision.level is AlertLevel.STRONG_WATCH


def test_opposing_candidates_create_conflict_and_suppress_alert() -> None:
    decision = score_candidate_signals(
        [
            _candidate(strategy="trend-pullback", direction=SignalDirection.BUY, score=70),
            _candidate(strategy="mean-reversion", direction=SignalDirection.SELL, score=65),
        ]
    )[0]

    assert decision.direction is SignalDirection.BUY
    assert decision.final_score == 37
    assert decision.level is AlertLevel.NO_ALERT
    assert decision.metadata.conflict_penalty == 33
    assert any("Opposing SELL candidates" in reason for reason in decision.reasons)
    assert any("alert suppressed" in reason for reason in decision.reasons)


def test_equal_opposing_scores_suppress_without_choosing_a_direction() -> None:
    decision = score_candidate_signals(
        [
            _candidate(direction=SignalDirection.BUY, score=70),
            _candidate(
                strategy="mean-reversion",
                direction=SignalDirection.SELL,
                score=70,
            ),
        ]
    )[0]

    assert decision.direction is None
    assert decision.final_score == 0
    assert decision.level is AlertLevel.NO_ALERT
    assert any("equal technical scores" in reason for reason in decision.reasons)


def test_nonpositive_opposing_score_does_not_boost_winning_direction() -> None:
    decision = score_candidate_signals(
        [
            _candidate(direction=SignalDirection.BUY, score=70),
            _candidate(
                strategy="mean-reversion",
                direction=SignalDirection.SELL,
                score=-10,
            ),
        ]
    )[0]

    assert decision.final_score == 70
    assert decision.metadata.conflict_penalty == 0


def test_duplicate_candidates_from_one_strategy_do_not_get_agreement_boost() -> None:
    decision = score_candidate_signals(
        [
            _candidate(strategy="trend-pullback", score=70),
            _candidate(strategy="trend-pullback", score=68),
        ]
    )[0]

    assert decision.final_score == 70
    assert decision.metadata.agreement_bonus == 0


def test_candidates_for_different_pairs_are_scored_independently() -> None:
    decisions = score_candidate_signals(
        [
            _candidate(pair="GBP/USD", direction=SignalDirection.SELL, score=80),
            _candidate(pair="EUR/USD", direction=SignalDirection.BUY, score=49),
        ]
    )

    assert [decision.pair for decision in decisions] == ["EUR/USD", "GBP/USD"]
    assert [decision.level for decision in decisions] == [
        AlertLevel.NO_ALERT,
        AlertLevel.STRONG_WATCH,
    ]


def test_candidates_for_different_timeframes_are_scored_independently() -> None:
    decisions = score_candidate_signals(
        [
            _candidate(timeframe="1h", score=80),
            _candidate(timeframe="15min", score=49),
        ]
    )

    assert [(decision.timeframe, decision.level) for decision in decisions] == [
        ("15min", AlertLevel.NO_ALERT),
        ("1h", AlertLevel.STRONG_WATCH),
    ]


def test_final_score_is_clamped_to_zero_and_one_hundred() -> None:
    low_decision = score_candidate_signals([_candidate(score=-10)])[0]
    high_decision = score_candidate_signals(
        [
            _candidate(strategy="trend-pullback", score=100),
            _candidate(strategy="breakout", score=100),
        ]
    )[0]

    assert low_decision.final_score == 0
    assert high_decision.final_score == 100


@pytest.mark.parametrize(
    ("score", "expected_level"),
    [
        (50, AlertLevel.WEAK_WATCH),
        (64, AlertLevel.WEAK_WATCH),
        (65, AlertLevel.WATCH),
        (79, AlertLevel.WATCH),
        (80, AlertLevel.STRONG_WATCH),
    ],
)
def test_default_alert_level_boundaries(
    score: int,
    expected_level: AlertLevel,
) -> None:
    assert score_candidate_signals([_candidate(score=score)])[0].level is expected_level


def test_alert_level_thresholds_are_configurable() -> None:
    config = SignalScorerConfig(
        strong_watch_threshold=90,
        watch_threshold=75,
        weak_watch_threshold=60,
    )

    decision = score_candidate_signals([_candidate(score=70)], config)[0]

    assert decision.level is AlertLevel.WEAK_WATCH


def test_decision_preserves_fields_reasons_and_candidate_metadata() -> None:
    breakout_metadata = CandidateSignalMetadata(
        signal_timestamp=datetime(2026, 8, 12, tzinfo=UTC),
        cooldown_key="breakout:EUR/USD:15min:BUY",
        reference_level=1.1,
        range_lookback=20,
    )
    breakout = _candidate(
        strategy="breakout",
        score=68,
        metadata=breakout_metadata,
    )
    trend_pullback = _candidate(strategy="trend-pullback", score=70)

    decision = score_candidate_signals([trend_pullback, breakout])[0]

    assert decision.pair == "EUR/USD"
    assert decision.timeframe == "15min"
    assert decision.direction is SignalDirection.BUY
    assert decision.level is AlertLevel.STRONG_WATCH
    assert decision.final_score == 80
    assert decision.contributing_strategies == ("breakout", "trend-pullback")
    assert "Same-direction agreement added 10 points." in decision.reasons
    assert "breakout: breakout setup" in decision.reasons
    assert "trend-pullback: trend-pullback setup" in decision.reasons
    assert decision.metadata.candidate_count == 2
    assert decision.metadata.supporting_candidate_count == 2
    assert decision.metadata.opposing_candidate_count == 0
    assert decision.metadata.technical_score == 80
    assert decision.metadata.agreement_bonus == 10
    assert decision.metadata.conflict_penalty == 0
    assert decision.metadata.suppressed is False
    assert decision.metadata.candidates == (breakout, trend_pullback)


@pytest.mark.parametrize(
    "config_overrides",
    [
        {"weak_watch_threshold": -1},
        {"strong_watch_threshold": 101},
        {"watch_threshold": True},
        {"strong_watch_threshold": 65, "watch_threshold": 65},
        {"agreement_bonus": -1},
        {"agreement_bonus": 1.5},
        {"opposing_score_penalty_fraction": -0.1},
        {"opposing_score_penalty_fraction": 1.1},
        {"opposing_score_penalty_fraction": float("nan")},
    ],
)
def test_invalid_scorer_config_is_rejected(
    config_overrides: dict[str, float | int],
) -> None:
    with pytest.raises(ValueError):
        SignalScorerConfig(**config_overrides)


def test_scorer_does_not_mutate_input_candidates() -> None:
    candidates = [
        _candidate(strategy="trend-pullback", score=70),
        _candidate(strategy="breakout", score=68),
    ]
    original_candidates = list(candidates)

    score_candidate_signals(candidates)

    assert candidates == original_candidates


def _candidate(
    *,
    pair: str = "EUR/USD",
    timeframe: str = "15min",
    strategy: str = "trend-pullback",
    direction: SignalDirection = SignalDirection.BUY,
    score: int = 70,
    metadata: CandidateSignalMetadata | None = None,
) -> CandidateSignal:
    return CandidateSignal(
        pair=pair,
        timeframe=timeframe,
        strategy=strategy,
        direction=direction,
        score=score,
        reasons=(f"{strategy} setup",),
        invalidation_level=1.0,
        metadata=metadata,
    )
