"""Deterministic scoring for technical candidate signals."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from forex_alert_bot.strategies import CandidateSignal, SignalDirection


class AlertLevel(StrEnum):
    """The outcome band assigned to a scored candidate group."""

    STRONG_WATCH = "Strong Watch"
    WATCH = "Watch"
    WEAK_WATCH = "Weak Watch"
    NO_ALERT = "No Alert"


@dataclass(frozen=True)
class AlertDecisionMetadata:
    """Scoring facts retained for formatting, logging, and later policy layers."""

    candidate_count: int
    supporting_candidate_count: int
    opposing_candidate_count: int
    technical_score: int
    agreement_bonus: int
    conflict_penalty: int
    suppressed: bool
    candidates: tuple[CandidateSignal, ...]


@dataclass(frozen=True)
class AlertDecision:
    """The scorer's final assessment for one pair and timeframe."""

    pair: str | None
    timeframe: str | None
    direction: SignalDirection | None
    level: AlertLevel
    final_score: int
    contributing_strategies: tuple[str, ...]
    reasons: tuple[str, ...]
    metadata: AlertDecisionMetadata


@dataclass(frozen=True)
class SignalScorerConfig:
    """Centralized thresholds for final technical alert decisions."""

    strong_watch_threshold: int = 80
    watch_threshold: int = 65
    weak_watch_threshold: int = 50
    agreement_bonus: int = 10
    opposing_score_penalty_fraction: float = 0.5

    def __post_init__(self) -> None:
        thresholds = (
            self.weak_watch_threshold,
            self.watch_threshold,
            self.strong_watch_threshold,
        )
        if any(
            isinstance(threshold, bool)
            or not isinstance(threshold, int)
            or not 0 <= threshold <= 100
            for threshold in thresholds
        ):
            raise ValueError("alert thresholds must be integers from 0 to 100")
        if not (self.weak_watch_threshold < self.watch_threshold < self.strong_watch_threshold):
            raise ValueError("alert thresholds must increase from Weak Watch to Strong Watch")
        if (
            isinstance(self.agreement_bonus, bool)
            or not isinstance(self.agreement_bonus, int)
            or self.agreement_bonus < 0
        ):
            raise ValueError("agreement_bonus must be a nonnegative integer")
        if (
            not math.isfinite(self.opposing_score_penalty_fraction)
            or not 0 <= self.opposing_score_penalty_fraction <= 1
        ):
            raise ValueError("opposing_score_penalty_fraction must be finite and from 0 to 1")


def score_candidate_signals(
    candidates: Sequence[CandidateSignal],
    config: SignalScorerConfig = SignalScorerConfig(),
) -> tuple[AlertDecision, ...]:
    """Score candidates into stable per-pair/timeframe decisions."""
    if not candidates:
        return (
            AlertDecision(
                pair=None,
                timeframe=None,
                direction=None,
                level=AlertLevel.NO_ALERT,
                final_score=0,
                contributing_strategies=(),
                reasons=("No candidate signals were provided.",),
                metadata=AlertDecisionMetadata(
                    candidate_count=0,
                    supporting_candidate_count=0,
                    opposing_candidate_count=0,
                    technical_score=0,
                    agreement_bonus=0,
                    conflict_penalty=0,
                    suppressed=True,
                    candidates=(),
                ),
            ),
        )

    grouped_candidates: defaultdict[tuple[str, str], list[CandidateSignal]] = defaultdict(list)
    for candidate in candidates:
        grouped_candidates[(candidate.pair, candidate.timeframe)].append(candidate)

    return tuple(
        _score_group(grouped_candidates[key], config) for key in sorted(grouped_candidates)
    )


def _score_group(
    candidates: Sequence[CandidateSignal],
    config: SignalScorerConfig,
) -> AlertDecision:
    candidate = candidates[0]
    sorted_candidates = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.strategy,
                item.direction.value,
                -item.score,
                item.invalidation_level,
                item.reasons,
            ),
        )
    )
    directional_scores = {
        direction: _technical_score(candidates, direction, config)
        for direction in SignalDirection
        if any(item.direction is direction for item in candidates)
    }
    if len(directional_scores) > 1 and len(set(directional_scores.values())) == 1:
        tied_score = next(iter(directional_scores.values()))
        strategies = tuple(sorted({item.strategy for item in sorted_candidates}))
        return AlertDecision(
            pair=candidate.pair,
            timeframe=candidate.timeframe,
            direction=None,
            level=AlertLevel.NO_ALERT,
            final_score=0,
            contributing_strategies=strategies,
            reasons=(
                *(
                    f"Conflict - {item.strategy}: {reason}"
                    for item in sorted_candidates
                    for reason in item.reasons
                ),
                "Opposing BUY and SELL candidates have equal technical scores "
                f"of {tied_score}; alert suppressed.",
            ),
            metadata=AlertDecisionMetadata(
                candidate_count=len(sorted_candidates),
                supporting_candidate_count=0,
                opposing_candidate_count=len(sorted_candidates),
                technical_score=tied_score,
                agreement_bonus=0,
                conflict_penalty=tied_score,
                suppressed=True,
                candidates=sorted_candidates,
            ),
        )
    direction = max(
        directional_scores,
        key=lambda item: (directional_scores[item], item.value),
    )
    opposing_score = max(
        (score for item, score in directional_scores.items() if item is not direction),
        default=0,
    )
    opposing_score = max(0, opposing_score)
    conflict_penalty = math.ceil(opposing_score * config.opposing_score_penalty_fraction)
    final_score = max(
        0,
        min(100, directional_scores[direction] - conflict_penalty),
    )
    supporting_candidates = tuple(item for item in sorted_candidates if item.direction is direction)
    opposing_candidates = tuple(
        item for item in sorted_candidates if item.direction is not direction
    )
    contributing_strategies = tuple(sorted({item.strategy for item in supporting_candidates}))
    agreement_bonus = config.agreement_bonus * max(0, len(contributing_strategies) - 1)
    level = _level_for_score(final_score, config)
    reasons = [
        f"{item.strategy}: {reason}" for item in supporting_candidates for reason in item.reasons
    ]
    if agreement_bonus:
        reasons.append(f"Same-direction agreement added {agreement_bonus} points.")
    if opposing_candidates:
        opposing_strategies = ", ".join(sorted({item.strategy for item in opposing_candidates}))
        reasons.append(
            f"Opposing {opposing_candidates[0].direction.value} candidates from "
            f"{opposing_strategies} reduced the score by {conflict_penalty} points."
        )
        reasons.extend(
            f"Conflict - {item.strategy}: {reason}"
            for item in opposing_candidates
            for reason in item.reasons
        )
    if level is AlertLevel.NO_ALERT:
        reasons.append(
            f"Final score {final_score} is below the Weak Watch threshold "
            f"of {config.weak_watch_threshold}; alert suppressed."
        )
    return AlertDecision(
        pair=candidate.pair,
        timeframe=candidate.timeframe,
        direction=direction,
        level=level,
        final_score=final_score,
        contributing_strategies=contributing_strategies,
        reasons=tuple(reasons),
        metadata=AlertDecisionMetadata(
            candidate_count=len(sorted_candidates),
            supporting_candidate_count=len(supporting_candidates),
            opposing_candidate_count=len(opposing_candidates),
            technical_score=directional_scores[direction],
            agreement_bonus=agreement_bonus,
            conflict_penalty=conflict_penalty,
            suppressed=level is AlertLevel.NO_ALERT,
            candidates=sorted_candidates,
        ),
    )


def _technical_score(
    candidates: Sequence[CandidateSignal],
    direction: SignalDirection,
    config: SignalScorerConfig,
) -> int:
    supporting_candidates = [item for item in candidates if item.direction is direction]
    contributing_strategy_count = len({item.strategy for item in supporting_candidates})
    return max(item.score for item in supporting_candidates) + (
        config.agreement_bonus * max(0, contributing_strategy_count - 1)
    )


def _level_for_score(score: int, config: SignalScorerConfig) -> AlertLevel:
    if score >= config.strong_watch_threshold:
        return AlertLevel.STRONG_WATCH
    if score >= config.watch_threshold:
        return AlertLevel.WATCH
    if score >= config.weak_watch_threshold:
        return AlertLevel.WEAK_WATCH
    return AlertLevel.NO_ALERT
