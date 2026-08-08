"""Deterministic technical indicators for normalized Forex candles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from forex_alert_bot.market_data import Candle


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Latest indicator values for one pair and timeframe."""

    timestamp: datetime
    close: float
    ema_20: float | None
    ema_50: float | None
    ema_200: float | None
    rsi_14: float | None
    atr_14: float | None
    adx_14: float | None


def calculate_indicator_snapshot(candles: Sequence[Candle]) -> IndicatorSnapshot | None:
    """Calculate the latest v1 indicator set without changing the input candles."""
    if not candles:
        return None

    closes = tuple(candle.close for candle in candles)
    latest = candles[-1]
    return IndicatorSnapshot(
        timestamp=latest.timestamp,
        close=latest.close,
        ema_20=calculate_ema(closes, period=20),
        ema_50=calculate_ema(closes, period=50),
        ema_200=calculate_ema(closes, period=200),
        rsi_14=calculate_rsi(closes, period=14),
        atr_14=calculate_atr(candles, period=14),
        adx_14=calculate_adx(candles, period=14),
    )


def calculate_ema(values: Sequence[float], *, period: int) -> float | None:
    """Return the latest exponential moving average, or None when history is short."""
    if len(values) < period:
        return None

    ema = sum(values[:period]) / period
    multiplier = 2 / (period + 1)
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def calculate_rsi(closes: Sequence[float], *, period: int = 14) -> float | None:
    """Return Wilder's latest relative strength index, or None when history is short."""
    if len(closes) <= period:
        return None

    changes = [current - previous for previous, current in pairwise(closes)]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period

    if average_gain == average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def calculate_atr(candles: Sequence[Candle], *, period: int = 14) -> float | None:
    """Return Wilder's latest average true range, or None when history is short."""
    if len(candles) < period:
        return None

    true_ranges = [candles[0].high - candles[0].low]
    for previous, current in pairwise(candles):
        true_ranges.append(_true_range(previous.close, current))

    average_true_range = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        average_true_range = ((average_true_range * (period - 1)) + true_range) / period
    return average_true_range


def calculate_adx(candles: Sequence[Candle], *, period: int = 14) -> float | None:
    """Return Wilder's latest average directional index, or None when history is short."""
    if len(candles) < period * 2:
        return None

    true_ranges: list[float] = []
    positive_moves: list[float] = []
    negative_moves: list[float] = []
    for previous, current in pairwise(candles):
        true_ranges.append(_true_range(previous.close, current))
        upward_move = current.high - previous.high
        downward_move = previous.low - current.low
        positive_moves.append(
            upward_move if upward_move > downward_move and upward_move > 0 else 0.0
        )
        negative_moves.append(
            downward_move if downward_move > upward_move and downward_move > 0 else 0.0
        )

    smoothed_true_range = sum(true_ranges[:period])
    smoothed_positive_move = sum(positive_moves[:period])
    smoothed_negative_move = sum(negative_moves[:period])
    dx_values = [_calculate_dx(smoothed_true_range, smoothed_positive_move, smoothed_negative_move)]

    for true_range, positive_move, negative_move in zip(
        true_ranges[period:], positive_moves[period:], negative_moves[period:]
    ):
        smoothed_true_range = smoothed_true_range - (smoothed_true_range / period) + true_range
        smoothed_positive_move = (
            smoothed_positive_move - (smoothed_positive_move / period) + positive_move
        )
        smoothed_negative_move = (
            smoothed_negative_move - (smoothed_negative_move / period) + negative_move
        )
        dx_values.append(
            _calculate_dx(smoothed_true_range, smoothed_positive_move, smoothed_negative_move)
        )

    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = ((adx * (period - 1)) + dx) / period
    return adx


def _true_range(previous_close: float, candle: Candle) -> float:
    return max(
        candle.high - candle.low,
        abs(candle.high - previous_close),
        abs(candle.low - previous_close),
    )


def _calculate_dx(true_range: float, positive_move: float, negative_move: float) -> float:
    if true_range == 0:
        return 0.0
    positive_index = 100 * positive_move / true_range
    negative_index = 100 * negative_move / true_range
    total_index = positive_index + negative_index
    if total_index == 0:
        return 0.0
    return 100 * abs(positive_index - negative_index) / total_index
