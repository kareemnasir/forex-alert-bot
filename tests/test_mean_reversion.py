from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from forex_alert_bot.indicators import IndicatorSnapshot
from forex_alert_bot.market_data import Candle
from forex_alert_bot.strategies import (
    CandidateSignal,
    CandidateSignalMetadata,
    MeanReversionConfig,
    SignalDirection,
    evaluate_mean_reversion,
)


@pytest.mark.parametrize(
    "config_overrides",
    [
        {"signal_score": -1},
        {"signal_score": 81},
        {"signal_score": float("nan")},
        {"range_lookback": 0},
        {"range_lookback": float("inf")},
        {"maximum_adx": -0.1},
        {"maximum_adx": 100.1},
        {"maximum_adx": float("nan")},
        {"edge_proximity_atr": -0.1},
        {"edge_proximity_atr": float("inf")},
        {"buy_rsi_max": -0.1},
        {"buy_rsi_max": 100.1},
        {"buy_rsi_max": float("nan")},
        {"sell_rsi_min": -0.1},
        {"sell_rsi_min": 100.1},
        {"sell_rsi_min": float("inf")},
        {"maximum_atr_range_fraction": -0.1},
        {"maximum_atr_range_fraction": float("nan")},
        {"invalidation_atr_buffer": -0.1},
        {"invalidation_atr_buffer": float("inf")},
    ],
)
def test_invalid_mean_reversion_config_is_rejected(
    config_overrides: dict[str, float | int],
) -> None:
    with pytest.raises(ValueError):
        MeanReversionConfig(**config_overrides)


def test_ranging_market_near_support_with_rsi_recovery_returns_buy_candidate() -> None:
    candles = _range_candles(latest_close=99.2)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(candles, previous_rsi=28.0, latest_rsi=34.0),
    )

    assert candidate == CandidateSignal(
        pair="EUR/USD",
        timeframe="15min",
        strategy="mean-reversion",
        direction=SignalDirection.BUY,
        score=65,
        reasons=(
            "ADX 18.0 indicates a ranging market (maximum 25.0).",
            "Latest close 99.20000 is 0.40 ATR from the 20-candle range support 99.00000.",
            "RSI recovered from 28.0 to 34.0 after an oversold reading.",
            "ATR is 0.25 of the recent range width.",
        ),
        invalidation_level=98.875,
        metadata=CandidateSignalMetadata(
            signal_timestamp=candles[-1].timestamp,
            cooldown_key="mean-reversion:EUR/USD:15min:BUY",
            reference_level=99.0,
            range_lookback=20,
        ),
    )


def test_ranging_market_near_resistance_with_rsi_rollover_returns_sell_candidate() -> None:
    candles = _range_candles(latest_close=100.8)

    candidate = evaluate_mean_reversion(
        pair="GBP/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(candles, previous_rsi=72.0, latest_rsi=66.0),
    )

    assert candidate == CandidateSignal(
        pair="GBP/USD",
        timeframe="15min",
        strategy="mean-reversion",
        direction=SignalDirection.SELL,
        score=65,
        reasons=(
            "ADX 18.0 indicates a ranging market (maximum 25.0).",
            "Latest close 100.80000 is 0.40 ATR from the 20-candle range resistance 101.00000.",
            "RSI rolled over from 72.0 to 66.0 after an overbought reading.",
            "ATR is 0.25 of the recent range width.",
        ),
        invalidation_level=101.125,
        metadata=CandidateSignalMetadata(
            signal_timestamp=candles[-1].timestamp,
            cooldown_key="mean-reversion:GBP/USD:15min:SELL",
            reference_level=101.0,
            range_lookback=20,
        ),
    )


@pytest.mark.parametrize(
    ("latest_close", "previous_rsi", "latest_rsi", "direction", "reason"),
    [
        (99.2, 40.0, 30.0, SignalDirection.BUY, "RSI is oversold at 30.0."),
        (100.8, 60.0, 70.0, SignalDirection.SELL, "RSI is overbought at 70.0."),
    ],
    ids=["oversold-buy", "overbought-sell"],
)
def test_range_edge_with_current_rsi_extreme_returns_candidate(
    latest_close: float,
    previous_rsi: float,
    latest_rsi: float,
    direction: SignalDirection,
    reason: str,
) -> None:
    candles = _range_candles(latest_close=latest_close)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(
            candles,
            previous_rsi=previous_rsi,
            latest_rsi=latest_rsi,
        ),
    )

    assert candidate is not None
    assert candidate.direction is direction
    assert reason in candidate.reasons


def test_trending_market_returns_no_candidate() -> None:
    candles = _range_candles(latest_close=99.2)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(
            candles,
            previous_rsi=28.0,
            latest_rsi=34.0,
            latest_adx=30.0,
        ),
    )

    assert candidate is None


def test_price_away_from_range_edges_returns_no_candidate() -> None:
    candles = _range_candles(latest_close=100.0)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(candles, previous_rsi=28.0, latest_rsi=34.0),
    )

    assert candidate is None


def test_unusually_high_volatility_returns_no_candidate() -> None:
    candles = _range_candles(latest_close=99.2)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(
            candles,
            previous_rsi=28.0,
            latest_rsi=34.0,
            latest_atr=1.1,
        ),
    )

    assert candidate is None


@pytest.mark.parametrize(
    ("latest_close", "previous_rsi", "latest_rsi"),
    [(98.8, 28.0, 34.0), (101.2, 72.0, 66.0)],
    ids=["buy-below-invalidation", "sell-above-invalidation"],
)
def test_candidate_already_beyond_invalidation_returns_no_candidate(
    latest_close: float,
    previous_rsi: float,
    latest_rsi: float,
) -> None:
    candles = _range_candles(latest_close=latest_close)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(
            candles,
            previous_rsi=previous_rsi,
            latest_rsi=latest_rsi,
        ),
    )

    assert candidate is None


def test_insufficient_history_returns_no_candidate() -> None:
    candles = _range_candles(latest_close=99.2)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles[1:],
        indicators=_indicators(candles, previous_rsi=28.0, latest_rsi=34.0),
    )

    assert candidate is None


def test_insufficient_indicator_history_returns_no_candidate() -> None:
    candles = _range_candles(latest_close=99.2)
    indicators = _indicators(candles, previous_rsi=28.0, latest_rsi=34.0)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=indicators[-1:],
    )

    assert candidate is None


def test_neutral_rsi_returns_no_candidate() -> None:
    candles = _range_candles(latest_close=99.2)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(candles, previous_rsi=45.0, latest_rsi=50.0),
    )

    assert candidate is None


def test_mean_reversion_accepts_inclusive_filter_boundaries() -> None:
    candles = _range_candles(latest_close=99.5)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=_indicators(
            candles,
            previous_rsi=28.0,
            latest_rsi=34.0,
            latest_adx=25.0,
            latest_atr=1.0,
        ),
    )

    assert candidate is not None


def test_mean_reversion_does_not_mutate_candles_indicators_or_config() -> None:
    candles = _range_candles(latest_close=99.2)
    indicators = list(_indicators(candles, previous_rsi=28.0, latest_rsi=34.0))
    config = MeanReversionConfig()
    original_candles = list(candles)
    original_indicators = list(indicators)

    evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=indicators,
        config=config,
    )

    assert candles == original_candles
    assert indicators == original_indicators
    assert config == MeanReversionConfig()


def test_stale_indicator_snapshot_returns_no_candidate() -> None:
    candles = _range_candles(latest_close=99.2)
    previous, latest = _indicators(candles, previous_rsi=28.0, latest_rsi=34.0)
    stale_latest = replace(latest, timestamp=candles[-2].timestamp)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=(previous, stale_latest),
    )

    assert candidate is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rsi_14", None),
        ("rsi_14", float("nan")),
        ("atr_14", None),
        ("atr_14", 0.0),
        ("atr_14", float("inf")),
        ("adx_14", None),
        ("adx_14", float("nan")),
    ],
)
def test_unusable_latest_indicator_returns_no_candidate(
    field: str,
    value: float | None,
) -> None:
    candles = _range_candles(latest_close=99.2)
    previous, latest = _indicators(candles, previous_rsi=28.0, latest_rsi=34.0)

    candidate = evaluate_mean_reversion(
        pair="EUR/USD",
        timeframe="15min",
        candles=candles,
        indicators=(previous, replace(latest, **{field: value})),
    )

    assert candidate is None


def _range_candles(*, latest_close: float) -> list[Candle]:
    start = datetime(2026, 8, 9, tzinfo=UTC)
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
            open=99.0,
            high=max(99.5, latest_close),
            low=min(98.9, latest_close),
            close=latest_close,
            volume=None,
        )
    )
    return candles


def _indicators(
    candles: list[Candle],
    *,
    previous_rsi: float,
    latest_rsi: float,
    latest_adx: float = 18.0,
    latest_atr: float = 0.5,
) -> tuple[IndicatorSnapshot, IndicatorSnapshot]:
    return (
        IndicatorSnapshot(
            timestamp=candles[-2].timestamp,
            close=candles[-2].close,
            ema_20=100.0,
            ema_50=100.0,
            ema_200=100.0,
            rsi_14=previous_rsi,
            atr_14=0.5,
            adx_14=18.0,
        ),
        IndicatorSnapshot(
            timestamp=candles[-1].timestamp,
            close=candles[-1].close,
            ema_20=100.0,
            ema_50=100.0,
            ema_200=100.0,
            rsi_14=latest_rsi,
            atr_14=latest_atr,
            adx_14=latest_adx,
        ),
    )
