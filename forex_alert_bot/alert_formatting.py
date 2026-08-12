"""Deterministic, Telegram-ready rendering for final alert decisions."""

from __future__ import annotations

import math
import re

from forex_alert_bot.scoring import AlertDecision, AlertLevel
from forex_alert_bot.strategies import CandidateSignal, SignalDirection

MAX_REASON_LENGTH = 160
MAX_REASONS = 3
_AGGRESSIVE_PHRASES = (
    (re.compile(r"\bbuy\s+now\b", re.IGNORECASE), "buy setup"),
    (re.compile(r"\bguaranteed\b", re.IGNORECASE), "unconfirmed"),
    (re.compile(r"\bprofit\b", re.IGNORECASE), "outcome"),
)


def format_alert_decision(decision: AlertDecision) -> str | None:
    """Return a concise alert message, or ``None`` when no alert should be sent."""
    if decision.level is AlertLevel.NO_ALERT:
        return None

    headline_parts = [part for part in (decision.pair, _direction(decision)) if part]
    headline_parts.append(decision.level.value)
    lines = [" ".join(headline_parts), f"Score: {decision.final_score}/100"]

    if decision.timeframe:
        lines.insert(1, f"Timeframe: {decision.timeframe}")
    if decision.contributing_strategies:
        strategies = " + ".join(
            _display_strategy(item) for item in decision.contributing_strategies
        )
        lines.append(f"Strategies: {strategies}")
    if decision.reasons:
        reasons = "; ".join(
            _clean_reason(reason) for reason in decision.reasons[:MAX_REASONS] if reason.strip()
        )
        if reasons:
            lines.append(f"Reasons: {reasons}")
    if invalidation := _invalidation_line(decision):
        lines.append(invalidation)

    lines.append("Manual decision only.")
    return "\n".join(lines)


def _direction(decision: AlertDecision) -> str | None:
    return decision.direction.value if decision.direction else None


def _display_strategy(strategy: str) -> str:
    return _safe_text(strategy.replace("-", " ")).title()


def _clean_reason(reason: str) -> str:
    cleaned = _safe_text(reason)
    if len(cleaned) <= MAX_REASON_LENGTH:
        return cleaned
    return f"{cleaned[: MAX_REASON_LENGTH - 3].rstrip()}..."


def _safe_text(text: str) -> str:
    cleaned = " ".join(text.split())
    for pattern, replacement in _AGGRESSIVE_PHRASES:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def _invalidation_line(decision: AlertDecision) -> str | None:
    candidate = _supporting_candidate(decision)
    if candidate is None or not math.isfinite(candidate.invalidation_level):
        return None

    relation = "above" if decision.direction is SignalDirection.SELL else "below"
    return f"Invalidation: {relation} {candidate.invalidation_level:.4f}"


def _supporting_candidate(decision: AlertDecision) -> CandidateSignal | None:
    if decision.direction is None:
        return None
    return min(
        (
            candidate
            for candidate in decision.metadata.candidates
            if candidate.direction is decision.direction
        ),
        key=lambda item: (-item.score, item.strategy, item.invalidation_level),
        default=None,
    )
