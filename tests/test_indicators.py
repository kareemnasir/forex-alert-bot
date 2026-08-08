from datetime import UTC, datetime, timedelta

import pytest

from forex_alert_bot.indicators import (
    IndicatorSnapshot,
    calculate_adx,
    calculate_atr,
    calculate_ema,
    calculate_indicator_snapshot,
    calculate_rsi,
)
from forex_alert_bot.market_data import Candle


def test_ema_uses_a_simple_average_seed_then_exponential_smoothing() -> None:
    assert calculate_ema([1.0, 2.0, 3.0, 4.0, 5.0], period=3) == pytest.approx(4.0)


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        ([1.0, 2.0, 3.0, 4.0], 100.0),
        ([4.0, 3.0, 2.0, 1.0], 0.0),
        ([2.0, 2.0, 2.0, 2.0], 50.0),
    ],
)
def test_rsi_has_clear_values_for_rising_falling_and_flat_prices(
    closes: list[float], expected: float
) -> None:
    assert calculate_rsi(closes, period=3) == pytest.approx(expected)


def test_rsi_applies_wilder_smoothing_after_the_seed_period() -> None:
    assert calculate_rsi([10.0, 11.0, 10.0, 12.0, 11.0, 13.0], period=3) == pytest.approx(75.0)


def test_atr_uses_high_low_and_previous_close_true_ranges() -> None:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    candles = [
        Candle(start, open=9.0, high=10.0, low=8.0, close=9.0, volume=None),
        Candle(
            start + timedelta(minutes=15),
            open=10.0,
            high=12.0,
            low=9.0,
            close=11.0,
            volume=None,
        ),
        Candle(
            start + timedelta(minutes=30),
            open=11.0,
            high=13.0,
            low=10.0,
            close=12.0,
            volume=None,
        ),
    ]

    assert calculate_atr(candles, period=3) == pytest.approx(8 / 3)


def test_atr_applies_wilder_smoothing_to_varying_true_ranges() -> None:
    assert calculate_atr(_mixed_candles()[:5], period=3) == pytest.approx(34 / 9)


@pytest.mark.parametrize(("step", "expected"), [(1.0, 100.0), (0.0, 0.0)])
def test_adx_distinguishes_a_steady_trend_from_a_flat_market(step: float, expected: float) -> None:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    candles = [
        Candle(
            start + timedelta(minutes=15 * index),
            open=100.0 + (step * index),
            high=101.0 + (step * index),
            low=99.0 + (step * index),
            close=100.5 + (step * index),
            volume=None,
        )
        for index in range(28)
    ]

    assert calculate_adx(candles, period=14) == pytest.approx(expected)


def test_adx_applies_wilder_smoothing_to_mixed_directional_moves() -> None:
    assert calculate_adx(_mixed_candles(), period=3) == pytest.approx(1700 / 81)


def test_indicator_snapshot_has_a_stable_strategy_ready_shape_without_mutating_candles() -> None:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    candles = [
        Candle(
            start + timedelta(minutes=15 * index),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=None,
        )
        for index in range(200)
    ]
    original_candles = list(candles)

    snapshot = calculate_indicator_snapshot(candles)

    assert snapshot == IndicatorSnapshot(
        timestamp=candles[-1].timestamp,
        close=100.0,
        ema_20=100.0,
        ema_50=100.0,
        ema_200=100.0,
        rsi_14=50.0,
        atr_14=2.0,
        adx_14=0.0,
    )
    assert candles == original_candles


def test_indicator_snapshot_marks_unavailable_values_for_short_history() -> None:
    candle = Candle(
        datetime(2026, 8, 8, tzinfo=UTC),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=None,
    )

    assert calculate_indicator_snapshot([]) is None
    assert calculate_indicator_snapshot([candle]) == IndicatorSnapshot(
        timestamp=candle.timestamp,
        close=100.0,
        ema_20=None,
        ema_50=None,
        ema_200=None,
        rsi_14=None,
        atr_14=None,
        adx_14=None,
    )


def _mixed_candles() -> list[Candle]:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    prices = [
        (9.0, 10.0, 8.0, 9.0),
        (10.0, 12.0, 9.0, 11.0),
        (10.0, 11.0, 7.0, 8.0),
        (11.0, 13.0, 10.0, 12.0),
        (10.0, 12.0, 8.0, 9.0),
        (12.0, 14.0, 11.0, 13.0),
        (11.0, 13.0, 9.0, 10.0),
    ]
    return [
        Candle(
            start + timedelta(minutes=15 * index),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=None,
        )
        for index, (open_price, high, low, close) in enumerate(prices)
    ]
