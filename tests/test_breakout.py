from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from forex_alert_bot.indicators import IndicatorSnapshot
from forex_alert_bot.market_data import Candle
from forex_alert_bot.strategies import (
    BreakoutConfig,
    CandidateSignal,
    CandidateSignalMetadata,
    SignalDirection,
    evaluate_breakout,
)


@pytest.mark.parametrize(
    "config_overrides",
    [
        {"signal_score": -1},
        {"signal_score": 81},
        {"signal_score": float("nan")},
        {"range_lookback": 0},
        {"range_lookback": float("inf")},
        {"minimum_body_atr_fraction": -0.1},
        {"minimum_body_atr_fraction": float("nan")},
        {"minimum_body_atr_fraction": float("inf")},
        {"maximum_extension_atr": -0.1},
        {"maximum_extension_atr": float("nan")},
        {"maximum_extension_atr": float("inf")},
        {"invalidation_atr_buffer": -0.1},
        {"invalidation_atr_buffer": float("nan")},
        {"invalidation_atr_buffer": float("inf")},
    ],
)
def test_invalid_breakout_config_is_rejected(
    config_overrides: dict[str, float | int],
) -> None:
    with pytest.raises(ValueError):
        BreakoutConfig(**config_overrides)


def test_close_above_prior_range_high_returns_buy_candidate() -> None:
    candles = _range_candles(
        latest_open=100.5,
        latest_high=102.0,
        latest_low=100.0,
        latest_close=101.5,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate == CandidateSignal(
        pair="EUR/USD",
        timeframe="15min",
        strategy="breakout",
        direction=SignalDirection.BUY,
        score=68,
        reasons=(
            "Latest close 101.50000 broke above the 20-candle range high 101.00000.",
            "Breakout candle body is 1.00 ATR.",
            "Breakout close is 0.50 ATR beyond the range high.",
        ),
        invalidation_level=100.75,
        metadata=CandidateSignalMetadata(
            signal_timestamp=candles[-1].timestamp,
            cooldown_key="breakout:EUR/USD:15min:BUY",
            reference_level=101.0,
            range_lookback=20,
        ),
    )


def test_close_below_prior_range_low_returns_sell_candidate() -> None:
    candles = _range_candles(
        latest_open=99.5,
        latest_high=100.0,
        latest_low=98.0,
        latest_close=98.5,
    )

    candidate = evaluate_breakout(
        pair="GBP/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate == CandidateSignal(
        pair="GBP/USD",
        timeframe="15min",
        strategy="breakout",
        direction=SignalDirection.SELL,
        score=68,
        reasons=(
            "Latest close 98.50000 broke below the 20-candle range low 99.00000.",
            "Breakout candle body is 1.00 ATR.",
            "Breakout close is 0.50 ATR beyond the range low.",
        ),
        invalidation_level=99.25,
        metadata=CandidateSignalMetadata(
            signal_timestamp=candles[-1].timestamp,
            cooldown_key="breakout:GBP/USD:15min:SELL",
            reference_level=99.0,
            range_lookback=20,
        ),
    )


def test_close_inside_recent_range_returns_no_candidate() -> None:
    candles = _range_candles(
        latest_open=100.0,
        latest_high=101.0,
        latest_low=99.0,
        latest_close=100.5,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate is None


def test_breakout_candle_with_small_body_returns_no_candidate() -> None:
    candles = _range_candles(
        latest_open=101.4,
        latest_high=101.6,
        latest_low=101.3,
        latest_close=101.5,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate is None


def test_breakout_close_too_far_beyond_range_returns_no_candidate() -> None:
    candles = _range_candles(
        latest_open=101.0,
        latest_high=103.0,
        latest_low=100.5,
        latest_close=102.5,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate is None


@pytest.mark.parametrize(
    ("latest_open", "latest_close"),
    [(101.0, 101.5), (101.0, 102.0)],
    ids=["minimum-body", "maximum-extension"],
)
def test_breakout_accepts_inclusive_atr_filter_boundaries(
    latest_open: float,
    latest_close: float,
) -> None:
    candles = _range_candles(
        latest_open=latest_open,
        latest_high=latest_close + 0.1,
        latest_low=100.5,
        latest_close=latest_close,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate is not None


def test_insufficient_range_history_returns_no_candidate() -> None:
    candles = _range_candles(
        latest_open=100.5,
        latest_high=102.0,
        latest_low=100.0,
        latest_close=101.5,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles[1:],
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate is None


def test_breakout_evaluation_does_not_mutate_candles_indicators_or_config() -> None:
    candles = _range_candles(
        latest_open=100.5,
        latest_high=102.0,
        latest_low=100.0,
        latest_close=101.5,
    )
    latest_indicators = _latest_indicators(candles, atr=1.0)
    config = BreakoutConfig()
    original_candles = list(candles)

    evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=latest_indicators,
        config=config,
    )

    assert candles == original_candles
    assert latest_indicators == _latest_indicators(candles, atr=1.0)
    assert config == BreakoutConfig()


def test_stale_latest_indicators_return_no_candidate() -> None:
    candles = _range_candles(
        latest_open=100.5,
        latest_high=102.0,
        latest_low=100.0,
        latest_close=101.5,
    )
    stale_indicators = replace(
        _latest_indicators(candles, atr=1.0),
        timestamp=candles[-2].timestamp,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=stale_indicators,
    )

    assert candidate is None


def test_non_increasing_candle_timestamps_return_no_candidate() -> None:
    candles = _range_candles(
        latest_open=100.5,
        latest_high=102.0,
        latest_low=100.0,
        latest_close=101.5,
    )
    candles[-1] = replace(candles[-1], timestamp=candles[-2].timestamp)

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=1.0),
    )

    assert candidate is None


@pytest.mark.parametrize("atr", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_unusable_latest_atr_returns_no_candidate(atr: float | None) -> None:
    candles = _range_candles(
        latest_open=100.5,
        latest_high=102.0,
        latest_low=100.0,
        latest_close=101.5,
    )

    candidate = evaluate_breakout(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        latest_indicators=_latest_indicators(candles, atr=atr),
    )

    assert candidate is None


def _range_candles(
    *,
    latest_open: float,
    latest_high: float,
    latest_low: float,
    latest_close: float,
) -> list[Candle]:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=start + timedelta(minutes=15 * index),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=None,
        )
        for index in range(20)
    ]
    candles.append(
        Candle(
            timestamp=start + timedelta(minutes=15 * 20),
            open=latest_open,
            high=latest_high,
            low=latest_low,
            close=latest_close,
            volume=None,
        )
    )
    return candles


def _latest_indicators(candles: list[Candle], *, atr: float | None) -> IndicatorSnapshot:
    latest = candles[-1]
    return IndicatorSnapshot(
        timestamp=latest.timestamp,
        close=latest.close,
        ema_20=100.0,
        ema_50=100.0,
        ema_200=100.0,
        rsi_14=50.0,
        atr_14=atr,
        adx_14=20.0,
    )
