from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from forex_alert_bot.cooldown import (
    AlertCooldownService,
    AlertHistoryEntry,
    CooldownPolicy,
    alert_fingerprint,
)
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.scoring import AlertDecision, AlertLevel, score_candidate_signals
from forex_alert_bot.strategies import CandidateSignal, SignalDirection

EVALUATED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def test_first_alert_is_allowed_when_no_history_exists() -> None:
    result = CooldownPolicy().evaluate(
        _decision(),
        recent_alerts=(),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is True
    assert result.matching_alert_id is None


def test_same_pair_direction_and_setup_inside_cooldown_is_blocked() -> None:
    decision = _decision()
    history = (
        AlertHistoryEntry(
            alert_id=41,
            fingerprint=alert_fingerprint(decision),
            sent_at=EVALUATED_AT - timedelta(minutes=30),
        ),
    )

    result = CooldownPolicy(cooldown_minutes=120).evaluate(
        decision,
        recent_alerts=history,
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is False
    assert result.matching_alert_id == 41


def test_same_pair_direction_and_setup_after_cooldown_is_allowed() -> None:
    decision = _decision()
    history = (_history_entry(decision, minutes_ago=121),)

    result = CooldownPolicy(cooldown_minutes=120).evaluate(
        decision,
        recent_alerts=history,
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is True


def test_alert_at_exact_cooldown_cutoff_is_allowed() -> None:
    decision = _decision()

    result = CooldownPolicy(cooldown_minutes=120).evaluate(
        decision,
        recent_alerts=(_history_entry(decision, minutes_ago=120),),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is True


def test_same_pair_with_opposite_direction_is_allowed() -> None:
    previous_decision = _decision(direction=SignalDirection.SELL)

    result = CooldownPolicy().evaluate(
        _decision(direction=SignalDirection.BUY),
        recent_alerts=(_history_entry(previous_decision),),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is True


def test_different_pair_is_allowed() -> None:
    previous_decision = _decision(pair="GBP/USD")

    result = CooldownPolicy().evaluate(
        _decision(pair="EUR/USD"),
        recent_alerts=(_history_entry(previous_decision),),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is True


def test_different_contributing_strategy_is_a_different_setup() -> None:
    previous_decision = _decision(strategy="trend-pullback")
    current_decision = _decision(strategy="breakout")

    assert alert_fingerprint(current_decision) != alert_fingerprint(previous_decision)
    assert (
        CooldownPolicy()
        .evaluate(
            current_decision,
            recent_alerts=(_history_entry(previous_decision),),
            evaluated_at=EVALUATED_AT,
        )
        .allowed
        is True
    )


def test_different_alert_level_is_a_different_fingerprint() -> None:
    watch_decision = _decision()
    strong_watch_decision = replace(watch_decision, level=AlertLevel.STRONG_WATCH)

    assert alert_fingerprint(strong_watch_decision) != alert_fingerprint(watch_decision)


def test_cooldown_duration_is_configurable() -> None:
    decision = _decision()
    history = (_history_entry(decision, minutes_ago=30),)

    short_window = CooldownPolicy(cooldown_minutes=20).evaluate(
        decision,
        recent_alerts=history,
        evaluated_at=EVALUATED_AT,
    )
    long_window = CooldownPolicy(cooldown_minutes=60).evaluate(
        decision,
        recent_alerts=history,
        evaluated_at=EVALUATED_AT,
    )

    assert short_window.allowed is True
    assert long_window.allowed is False


def test_zero_minute_cooldown_disables_duplicate_blocking() -> None:
    decision = _decision()
    history = (
        AlertHistoryEntry(
            alert_id=41,
            fingerprint=alert_fingerprint(decision),
            sent_at=EVALUATED_AT,
        ),
    )

    result = CooldownPolicy(cooldown_minutes=0).evaluate(
        decision,
        recent_alerts=history,
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is True


def test_negative_cooldown_duration_is_rejected() -> None:
    with pytest.raises(ValueError, match="cooldown_minutes"):
        CooldownPolicy(cooldown_minutes=-1)


def test_policy_does_not_mutate_decision_or_history() -> None:
    decision = _decision()
    history = (_history_entry(decision),)
    original_decision = deepcopy(decision)
    original_history = deepcopy(history)

    CooldownPolicy().evaluate(
        decision,
        recent_alerts=history,
        evaluated_at=EVALUATED_AT,
    )

    assert decision == original_decision
    assert history == original_history


def test_skipped_duplicate_is_recorded_for_inspection(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    decision = _decision()
    sent_run_id = database.start_run(dry_run=False)
    sent_alert_id = _record_sent_alert(database, sent_run_id, decision)
    current_run_id = database.start_run(dry_run=False)

    result = AlertCooldownService(database, CooldownPolicy()).evaluate(
        current_run_id,
        decision,
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is False
    assert database.get_alert_skips(current_run_id) == [
        {
            "run_id": current_run_id,
            "matching_alert_id": sent_alert_id,
            "fingerprint": alert_fingerprint(decision),
            "pair": "EUR/USD",
            "direction": "BUY",
            "timeframe": "15min",
            "alert_level": "Watch",
            "contributing_strategies": ["trend-pullback"],
            "reason": result.reason,
            "skipped_at": EVALUATED_AT.isoformat(),
        }
    ]


def test_allowed_service_evaluation_does_not_record_a_skip(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    run_id = database.start_run(dry_run=False)

    result = AlertCooldownService(database, CooldownPolicy()).evaluate(
        run_id,
        _decision(),
        evaluated_at=EVALUATED_AT,
    )

    assert result.allowed is True
    assert database.get_alert_skips(run_id) == []


def _decision(
    *,
    pair: str = "EUR/USD",
    direction: SignalDirection = SignalDirection.BUY,
    strategy: str = "trend-pullback",
) -> AlertDecision:
    return score_candidate_signals(
        (
            CandidateSignal(
                pair=pair,
                timeframe="15min",
                strategy=strategy,
                direction=direction,
                score=70,
                reasons=(f"{strategy} setup",),
                invalidation_level=1.08,
            ),
        )
    )[0]


def _history_entry(
    decision: AlertDecision,
    *,
    alert_id: int = 41,
    minutes_ago: int = 30,
) -> AlertHistoryEntry:
    return AlertHistoryEntry(
        alert_id=alert_id,
        fingerprint=alert_fingerprint(decision),
        sent_at=EVALUATED_AT - timedelta(minutes=minutes_ago),
    )


def _record_sent_alert(
    database: SQLiteLog,
    run_id: int,
    decision: AlertDecision,
) -> int:
    candidate_id = database.record_candidate_signal(
        run_id,
        strategy=decision.contributing_strategies[0],
        pair=decision.pair or "",
        direction=decision.direction.value if decision.direction else "",
        timeframe=decision.timeframe,
        payload={},
    )
    news_analysis_id = database.record_news_analysis(
        run_id,
        candidate_signal_id=candidate_id,
        input_payload={},
        output_payload={},
    )
    return database.record_alert(
        run_id,
        candidate_signal_id=candidate_id,
        news_analysis_id=news_analysis_id,
        message="EUR/USD BUY Watch",
        fingerprint=alert_fingerprint(decision),
        sent_at=EVALUATED_AT - timedelta(minutes=30),
    )
