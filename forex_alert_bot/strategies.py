"""Deterministic candidate-signal generation for Forex strategies."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from forex_alert_bot.indicators import IndicatorSnapshot
from forex_alert_bot.market_data import Candle

TREND_PULLBACK_STRATEGY = "trend-pullback"
BREAKOUT_STRATEGY = "breakout"


class SignalDirection(StrEnum):
    """The market direction suggested by a technical candidate."""

    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class CandidateSignalMetadata:
    """Stable setup facts for future candidate cooldown and deduplication."""

    signal_timestamp: datetime
    cooldown_key: str
    reference_level: float
    range_lookback: int


@dataclass(frozen=True)
class CandidateSignal:
    """An inspectable technical setup for later scoring and alert decisions."""

    pair: str
    timeframe: str
    strategy: str
    direction: SignalDirection
    score: int
    reasons: tuple[str, ...]
    invalidation_level: float
    metadata: CandidateSignalMetadata | None = None


@dataclass(frozen=True)
class BreakoutConfig:
    """Centralized thresholds for the v1 Breakout rules."""

    signal_score: int = 68
    range_lookback: int = 20
    minimum_body_atr_fraction: float = 0.5
    maximum_extension_atr: float = 1.0
    invalidation_atr_buffer: float = 0.25

    def __post_init__(self) -> None:
        if (
            isinstance(self.signal_score, bool)
            or not isinstance(self.signal_score, int)
            or not 0 <= self.signal_score <= 80
        ):
            raise ValueError("signal_score must be an integer from 0 to 80")
        if (
            isinstance(self.range_lookback, bool)
            or not isinstance(self.range_lookback, int)
            or self.range_lookback < 1
        ):
            raise ValueError("range_lookback must be a positive integer")
        if not math.isfinite(self.minimum_body_atr_fraction) or self.minimum_body_atr_fraction < 0:
            raise ValueError("minimum_body_atr_fraction must be finite and nonnegative")
        if not math.isfinite(self.maximum_extension_atr) or self.maximum_extension_atr < 0:
            raise ValueError("maximum_extension_atr must be finite and nonnegative")
        if not math.isfinite(self.invalidation_atr_buffer) or self.invalidation_atr_buffer < 0:
            raise ValueError("invalidation_atr_buffer must be finite and nonnegative")


@dataclass(frozen=True)
class TrendPullbackConfig:
    """Centralized thresholds for the v1 Trend Pullback rules."""

    signal_score: int = 70
    buy_rsi_dip_max: float = 45.0
    sell_rsi_bounce_min: float = 55.0
    pullback_atr_tolerance: float = 0.25
    swing_lookback: int = 5
    invalidation_atr_buffer: float = 0.25

    def __post_init__(self) -> None:
        if (
            isinstance(self.signal_score, bool)
            or not isinstance(self.signal_score, int)
            or not 0 <= self.signal_score <= 80
        ):
            raise ValueError("signal_score must be an integer from 0 to 80")
        if not math.isfinite(self.buy_rsi_dip_max) or not 0 <= self.buy_rsi_dip_max <= 100:
            raise ValueError("buy_rsi_dip_max must be finite and from 0 to 100")
        if not math.isfinite(self.sell_rsi_bounce_min) or not 0 <= self.sell_rsi_bounce_min <= 100:
            raise ValueError("sell_rsi_bounce_min must be finite and from 0 to 100")
        if not math.isfinite(self.pullback_atr_tolerance) or self.pullback_atr_tolerance < 0:
            raise ValueError("pullback_atr_tolerance must be finite and nonnegative")
        if (
            isinstance(self.swing_lookback, bool)
            or not isinstance(self.swing_lookback, int)
            or self.swing_lookback < 1
        ):
            raise ValueError("swing_lookback must be a positive integer")
        if not math.isfinite(self.invalidation_atr_buffer) or self.invalidation_atr_buffer < 0:
            raise ValueError("invalidation_atr_buffer must be finite and nonnegative")


def evaluate_breakout(
    *,
    pair: str,
    timeframe: str,
    candles: Sequence[Candle],
    latest_indicators: IndicatorSnapshot,
    config: BreakoutConfig = BreakoutConfig(),
) -> CandidateSignal | None:
    """Return a fresh range-breakout candidate, or None when no breakout exists."""
    if len(candles) < config.range_lookback + 1:
        return None

    breakout_window = candles[-(config.range_lookback + 1) :]
    if any(
        previous.timestamp >= current.timestamp
        for previous, current in zip(breakout_window, breakout_window[1:])
    ):
        return None

    latest = breakout_window[-1]
    if latest_indicators.timestamp != latest.timestamp or latest_indicators.close != latest.close:
        return None
    atr = latest_indicators.atr_14
    if atr is None or not math.isfinite(atr) or atr <= 0:
        return None
    recent_range = breakout_window[:-1]
    range_high = max(candle.high for candle in recent_range)
    range_low = min(candle.low for candle in recent_range)
    if latest.close > range_high:
        direction = SignalDirection.BUY
        reference_level = range_high
        boundary_name = "high"
        breakout_distance = latest.close - range_high
        invalidation_level = range_high - (atr * config.invalidation_atr_buffer)
    elif latest.close < range_low:
        direction = SignalDirection.SELL
        reference_level = range_low
        boundary_name = "low"
        breakout_distance = range_low - latest.close
        invalidation_level = range_low + (atr * config.invalidation_atr_buffer)
    else:
        return None

    body_atr = abs(latest.close - latest.open) / atr
    if body_atr < config.minimum_body_atr_fraction:
        return None
    extension_atr = breakout_distance / atr
    if extension_atr > config.maximum_extension_atr:
        return None
    return CandidateSignal(
        pair=pair,
        timeframe=timeframe,
        strategy=BREAKOUT_STRATEGY,
        direction=direction,
        score=config.signal_score,
        reasons=(
            f"Latest close {latest.close:.5f} broke "
            f"{'above' if direction is SignalDirection.BUY else 'below'} the "
            f"{config.range_lookback}-candle range {boundary_name} {reference_level:.5f}.",
            f"Breakout candle body is {body_atr:.2f} ATR.",
            f"Breakout close is {extension_atr:.2f} ATR beyond the range {boundary_name}.",
        ),
        invalidation_level=invalidation_level,
        metadata=CandidateSignalMetadata(
            signal_timestamp=latest.timestamp,
            cooldown_key=(f"{BREAKOUT_STRATEGY}:{pair}:{timeframe}:{direction.value}"),
            reference_level=reference_level,
            range_lookback=config.range_lookback,
        ),
    )


def evaluate_trend_pullback(
    *,
    pair: str,
    timeframe: str,
    higher_indicators: IndicatorSnapshot,
    lower_indicators: Sequence[IndicatorSnapshot],
    lower_candles: Sequence[Candle],
    config: TrendPullbackConfig = TrendPullbackConfig(),
) -> CandidateSignal | None:
    """Return a clear Trend Pullback candidate, or None when rules do not agree."""
    if len(lower_indicators) < 2 or len(lower_candles) < max(2, config.swing_lookback):
        return None

    previous = lower_indicators[-2]
    latest = lower_indicators[-1]
    if not _has_required_indicators(higher_indicators, previous, latest):
        return None
    if (
        previous.timestamp != lower_candles[-2].timestamp
        or latest.timestamp != lower_candles[-1].timestamp
        or previous.timestamp >= latest.timestamp
        or previous.close != lower_candles[-2].close
        or latest.close != lower_candles[-1].close
    ):
        return None

    if not _is_pullback_near_ema_zone(
        lower_candles[-2], previous, tolerance=config.pullback_atr_tolerance
    ):
        return None

    if higher_indicators.ema_50 > higher_indicators.ema_200:
        return _buy_candidate(pair, timeframe, previous, latest, lower_candles, config)
    if higher_indicators.ema_50 < higher_indicators.ema_200:
        return _sell_candidate(pair, timeframe, previous, latest, lower_candles, config)
    return None


def _has_required_indicators(
    higher: IndicatorSnapshot,
    previous: IndicatorSnapshot,
    latest: IndicatorSnapshot,
) -> bool:
    return all(
        value is not None
        for value in (
            higher.ema_50,
            higher.ema_200,
            previous.ema_20,
            previous.ema_50,
            previous.rsi_14,
            previous.atr_14,
            latest.ema_20,
            latest.ema_50,
            latest.rsi_14,
            latest.atr_14,
        )
    )


def _is_pullback_near_ema_zone(
    candle: Candle,
    indicators: IndicatorSnapshot,
    *,
    tolerance: float,
) -> bool:
    margin = indicators.atr_14 * tolerance
    ema_low = min(indicators.ema_20, indicators.ema_50)
    ema_high = max(indicators.ema_20, indicators.ema_50)
    return candle.low <= ema_high + margin and candle.high >= ema_low - margin


def _buy_candidate(
    pair: str,
    timeframe: str,
    previous: IndicatorSnapshot,
    latest: IndicatorSnapshot,
    candles: Sequence[Candle],
    config: TrendPullbackConfig,
) -> CandidateSignal | None:
    if not (
        previous.rsi_14 <= config.buy_rsi_dip_max
        and latest.rsi_14 > previous.rsi_14
        and latest.close > previous.close
        and latest.close > latest.ema_20
    ):
        return None

    invalidation = min(candle.low for candle in candles[-config.swing_lookback :]) - (
        latest.atr_14 * config.invalidation_atr_buffer
    )
    return CandidateSignal(
        pair=pair,
        timeframe=timeframe,
        strategy=TREND_PULLBACK_STRATEGY,
        direction=SignalDirection.BUY,
        score=config.signal_score,
        reasons=(
            "Higher-timeframe EMA 50 is above EMA 200.",
            "Lower-timeframe price pulled back near EMA 20/50.",
            f"RSI recovered from {previous.rsi_14:.1f} to {latest.rsi_14:.1f}.",
            "Latest close resumed upward momentum.",
        ),
        invalidation_level=invalidation,
    )


def _sell_candidate(
    pair: str,
    timeframe: str,
    previous: IndicatorSnapshot,
    latest: IndicatorSnapshot,
    candles: Sequence[Candle],
    config: TrendPullbackConfig,
) -> CandidateSignal | None:
    if not (
        previous.rsi_14 >= config.sell_rsi_bounce_min
        and latest.rsi_14 < previous.rsi_14
        and latest.close < previous.close
        and latest.close < latest.ema_20
    ):
        return None

    invalidation = max(candle.high for candle in candles[-config.swing_lookback :]) + (
        latest.atr_14 * config.invalidation_atr_buffer
    )
    return CandidateSignal(
        pair=pair,
        timeframe=timeframe,
        strategy=TREND_PULLBACK_STRATEGY,
        direction=SignalDirection.SELL,
        score=config.signal_score,
        reasons=(
            "Higher-timeframe EMA 50 is below EMA 200.",
            "Lower-timeframe price pulled back near EMA 20/50.",
            f"RSI weakened from {previous.rsi_14:.1f} to {latest.rsi_14:.1f}.",
            "Latest close resumed downward momentum.",
        ),
        invalidation_level=invalidation,
    )
