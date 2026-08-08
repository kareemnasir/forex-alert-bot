from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from forex_alert_bot.indicators import IndicatorSnapshot
from forex_alert_bot.market_data import Candle
from forex_alert_bot.strategies import (
    CandidateSignal,
    SignalDirection,
    TrendPullbackConfig,
    evaluate_trend_pullback,
)


@pytest.mark.parametrize(
    "config_overrides",
    [
        {"signal_score": -1},
        {"signal_score": 81},
        {"signal_score": float("nan")},
        {"buy_rsi_dip_max": -0.1},
        {"buy_rsi_dip_max": 100.1},
        {"buy_rsi_dip_max": float("nan")},
        {"sell_rsi_bounce_min": -0.1},
        {"sell_rsi_bounce_min": 100.1},
        {"sell_rsi_bounce_min": float("inf")},
        {"pullback_atr_tolerance": -0.1},
        {"pullback_atr_tolerance": float("nan")},
        {"pullback_atr_tolerance": float("inf")},
        {"swing_lookback": 0},
        {"swing_lookback": float("inf")},
        {"invalidation_atr_buffer": -0.1},
        {"invalidation_atr_buffer": float("nan")},
        {"invalidation_atr_buffer": float("inf")},
    ],
)
def test_invalid_trend_pullback_config_is_rejected(
    config_overrides: dict[str, float | int],
) -> None:
    with pytest.raises(ValueError):
        TrendPullbackConfig(**config_overrides)


def test_trend_pullback_config_accepts_inclusive_boundaries() -> None:
    assert (
        TrendPullbackConfig(
            signal_score=0,
            buy_rsi_dip_max=0.0,
            sell_rsi_bounce_min=100.0,
            pullback_atr_tolerance=0.0,
            swing_lookback=1,
            invalidation_atr_buffer=0.0,
        ).signal_score
        == 0
    )
    assert (
        TrendPullbackConfig(
            signal_score=80,
            buy_rsi_dip_max=100.0,
            sell_rsi_bounce_min=0.0,
        ).signal_score
        == 80
    )


def test_bullish_trend_and_pullback_recovery_returns_buy_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=_bullish_lower_indicators(candles),
        lower_candles=candles,
    )

    assert candidate == CandidateSignal(
        pair="EUR/USD",
        timeframe="15min",
        strategy="trend-pullback",
        direction=SignalDirection.BUY,
        score=70,
        reasons=(
            "Higher-timeframe EMA 50 is above EMA 200.",
            "Lower-timeframe price pulled back near EMA 20/50.",
            "RSI recovered from 44.0 to 50.0.",
            "Latest close resumed upward momentum.",
        ),
        invalidation_level=97.5,
    )


def test_bearish_trend_and_pullback_rejection_returns_sell_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=98.5)

    candidate = evaluate_trend_pullback(
        pair="GBP/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=90.0, ema_50=95.0, ema_200=100.0),
        lower_indicators=_bearish_lower_indicators(candles),
        lower_candles=candles,
    )

    assert candidate == CandidateSignal(
        pair="GBP/USD",
        timeframe="15min",
        strategy="trend-pullback",
        direction=SignalDirection.SELL,
        score=70,
        reasons=(
            "Higher-timeframe EMA 50 is below EMA 200.",
            "Lower-timeframe price pulled back near EMA 20/50.",
            "RSI weakened from 56.0 to 50.0.",
            "Latest close resumed downward momentum.",
        ),
        invalidation_level=102.5,
    )


def test_unclear_higher_timeframe_trend_returns_no_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=100.0, ema_50=100.0, ema_200=100.0),
        lower_indicators=_bullish_lower_indicators(candles),
        lower_candles=candles,
    )

    assert candidate is None


def test_lower_timeframe_without_recovery_returns_no_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    previous, latest = _bullish_lower_indicators(candles)
    latest_without_recovery = replace(latest, rsi_14=42.0)

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=(previous, latest_without_recovery),
        lower_candles=candles,
    )

    assert candidate is None


def test_price_outside_ema_zone_returns_no_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    previous, latest = _bullish_lower_indicators(candles)
    previous_outside_zone = replace(previous, ema_20=110.0, ema_50=111.0)

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=(previous_outside_zone, latest),
        lower_candles=candles,
    )

    assert candidate is None


def test_bullish_trend_with_bearish_entry_conditions_returns_no_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=98.5)

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=_bearish_lower_indicators(candles),
        lower_candles=candles,
    )

    assert candidate is None


def test_insufficient_history_or_indicators_returns_no_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    previous, latest = _bullish_lower_indicators(candles)

    assert (
        evaluate_trend_pullback(
            pair="EUR/USD",
            timeframe="15min",
            higher_indicators=_snapshot(close=110.0, ema_50=None, ema_200=None),
            lower_indicators=(previous, latest),
            lower_candles=candles,
        )
        is None
    )
    assert (
        evaluate_trend_pullback(
            pair="EUR/USD",
            timeframe="15min",
            higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
            lower_indicators=(previous, latest),
            lower_candles=candles[-2:],
        )
        is None
    )


def test_one_candle_history_returns_no_candidate_with_one_candle_lookback() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    previous, latest = _bullish_lower_indicators(candles)

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=(previous, latest),
        lower_candles=candles[-1:],
        config=TrendPullbackConfig(swing_lookback=1),
    )

    assert candidate is None


@pytest.mark.parametrize("snapshot_index", [0, 1])
def test_snapshot_close_mismatch_returns_no_candidate(snapshot_index: int) -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    lower_indicators = list(_bullish_lower_indicators(candles))
    lower_indicators[snapshot_index] = replace(
        lower_indicators[snapshot_index],
        close=lower_indicators[snapshot_index].close + 1.0,
    )

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=lower_indicators,
        lower_candles=candles,
    )

    assert candidate is None


def test_snapshot_timestamp_mismatch_returns_no_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    previous, latest = _bullish_lower_indicators(candles)
    mismatched_previous = replace(
        previous,
        timestamp=previous.timestamp + timedelta(minutes=1),
    )

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=(mismatched_previous, latest),
        lower_candles=candles,
    )

    assert candidate is None


def test_non_increasing_lower_timestamps_return_no_candidate() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    candles[-1] = replace(candles[-1], timestamp=candles[-2].timestamp)
    lower_indicators = _bullish_lower_indicators(candles)

    candidate = evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=_snapshot(close=110.0, ema_50=105.0, ema_200=100.0),
        lower_indicators=lower_indicators,
        lower_candles=candles,
    )

    assert candidate is None


def test_strategy_does_not_mutate_candles_indicators_or_config() -> None:
    candles = _lower_candles(previous_close=100.0, latest_close=101.5)
    lower_indicators = list(_bullish_lower_indicators(candles))
    higher_indicators = _snapshot(close=110.0, ema_50=105.0, ema_200=100.0)
    config = TrendPullbackConfig()
    original_candles = list(candles)
    original_indicators = list(lower_indicators)

    evaluate_trend_pullback(
        pair="EUR/USD",
        timeframe="15min",
        higher_indicators=higher_indicators,
        lower_indicators=lower_indicators,
        lower_candles=candles,
        config=config,
    )

    assert candles == original_candles
    assert lower_indicators == original_indicators
    assert config == TrendPullbackConfig()


def _bullish_lower_indicators(
    candles: list[Candle],
) -> tuple[IndicatorSnapshot, IndicatorSnapshot]:
    return (
        _snapshot(
            timestamp=candles[-2].timestamp,
            close=100.0,
            ema_20=100.2,
            ema_50=99.8,
            rsi=44.0,
            atr=2.0,
        ),
        _snapshot(
            timestamp=candles[-1].timestamp,
            close=101.5,
            ema_20=100.5,
            ema_50=100.0,
            rsi=50.0,
            atr=2.0,
        ),
    )


def _bearish_lower_indicators(
    candles: list[Candle],
) -> tuple[IndicatorSnapshot, IndicatorSnapshot]:
    return (
        _snapshot(
            timestamp=candles[-2].timestamp,
            close=100.0,
            ema_20=99.8,
            ema_50=100.2,
            rsi=56.0,
            atr=2.0,
        ),
        _snapshot(
            timestamp=candles[-1].timestamp,
            close=98.5,
            ema_20=99.5,
            ema_50=100.0,
            rsi=50.0,
            atr=2.0,
        ),
    )


def _snapshot(
    *,
    close: float,
    ema_50: float | None,
    ema_200: float | None = 90.0,
    timestamp: datetime | None = None,
    ema_20: float | None = 100.0,
    rsi: float | None = 50.0,
    atr: float | None = 2.0,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        timestamp=timestamp or datetime(2026, 8, 8, tzinfo=UTC),
        close=close,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=ema_200,
        rsi_14=rsi,
        atr_14=atr,
        adx_14=25.0,
    )


def _lower_candles(*, previous_close: float, latest_close: float) -> list[Candle]:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    candles = [
        Candle(
            timestamp=start + timedelta(minutes=15 * index),
            open=99.0,
            high=102.0,
            low=98.0,
            close=99.0,
            volume=None,
        )
        for index in range(3)
    ]
    candles.extend(
        [
            Candle(
                timestamp=start + timedelta(minutes=45),
                open=100.5,
                high=101.0,
                low=99.5,
                close=previous_close,
                volume=None,
            ),
            Candle(
                timestamp=start + timedelta(minutes=60),
                open=previous_close,
                high=max(previous_close, latest_close) + 1.0,
                low=min(previous_close, latest_close) - 1.0,
                close=latest_close,
                volume=None,
            ),
        ]
    )
    return candles
