"""Deterministic duplicate-alert cooldown policy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from forex_alert_bot.config import DEFAULT_ALERT_COOLDOWN_MINUTES
from forex_alert_bot.scoring import AlertDecision, AlertLevel
from forex_alert_bot.strategies import SignalDirection


@dataclass(frozen=True)
class AlertHistoryEntry:
    """One previously sent alert considered by the cooldown policy."""

    alert_id: int
    fingerprint: str
    sent_at: datetime


@dataclass(frozen=True)
class CooldownEvaluation:
    """The inspectable outcome of evaluating one alert decision."""

    fingerprint: str
    matching_alert_id: int | None
    reason: str

    @property
    def allowed(self) -> bool:
        """Return whether no recent matching alert blocked the decision."""
        return self.matching_alert_id is None


@dataclass(frozen=True)
class DuplicateAlertSkip:
    """A blocked duplicate retained for later inspection."""

    matching_alert_id: int
    fingerprint: str
    pair: str
    direction: SignalDirection
    timeframe: str
    alert_level: AlertLevel
    contributing_strategies: tuple[str, ...]
    reason: str
    skipped_at: datetime


class AlertHistoryStore(Protocol):
    """Persistence operations needed by the cooldown service."""

    def get_recent_alerts(
        self,
        *,
        fingerprint: str,
        since: datetime,
        until: datetime,
    ) -> tuple[AlertHistoryEntry, ...]: ...

    def record_alert_skip(self, run_id: int, skip: DuplicateAlertSkip) -> int: ...


@dataclass(frozen=True)
class CooldownPolicy:
    """Decide whether an alert is distinct from recent sent alerts."""

    cooldown_minutes: int = DEFAULT_ALERT_COOLDOWN_MINUTES

    def __post_init__(self) -> None:
        if (
            isinstance(self.cooldown_minutes, bool)
            or not isinstance(self.cooldown_minutes, int)
            or self.cooldown_minutes < 0
        ):
            raise ValueError("cooldown_minutes must be a nonnegative integer")

    def evaluate(
        self,
        decision: AlertDecision,
        recent_alerts: Sequence[AlertHistoryEntry],
        *,
        evaluated_at: datetime,
    ) -> CooldownEvaluation:
        """Return whether ``decision`` may be sent without mutating inputs."""
        fingerprint = alert_fingerprint(decision)
        cutoff = evaluated_at - timedelta(minutes=self.cooldown_minutes)
        matching_alert = max(
            (
                alert
                for alert in recent_alerts
                if alert.fingerprint == fingerprint and cutoff < alert.sent_at <= evaluated_at
            ),
            key=lambda alert: (alert.sent_at, alert.alert_id),
            default=None,
        )
        if matching_alert is not None:
            return CooldownEvaluation(
                fingerprint=fingerprint,
                matching_alert_id=matching_alert.alert_id,
                reason=(
                    f"Matching alert {matching_alert.alert_id} was sent during the "
                    f"{self.cooldown_minutes}-minute cooldown window."
                ),
            )
        return CooldownEvaluation(
            fingerprint=fingerprint,
            matching_alert_id=None,
            reason="No matching alert was sent during the cooldown window.",
        )


@dataclass(frozen=True)
class AlertCooldownService:
    """Check persisted alert history and record blocked duplicates."""

    history_store: AlertHistoryStore
    policy: CooldownPolicy = CooldownPolicy()

    def evaluate(
        self,
        run_id: int,
        decision: AlertDecision,
        *,
        evaluated_at: datetime,
    ) -> CooldownEvaluation:
        """Evaluate one decision against SQLite-backed alert history."""
        fingerprint = alert_fingerprint(decision)
        history = self.history_store.get_recent_alerts(
            fingerprint=fingerprint,
            since=evaluated_at - timedelta(minutes=self.policy.cooldown_minutes),
            until=evaluated_at,
        )
        result = self.policy.evaluate(
            decision,
            recent_alerts=history,
            evaluated_at=evaluated_at,
        )
        if not result.allowed:
            if (
                result.matching_alert_id is None
                or decision.pair is None
                or decision.direction is None
                or decision.timeframe is None
            ):
                raise ValueError("Blocked alerts must have complete duplicate metadata")
            self.history_store.record_alert_skip(
                run_id,
                DuplicateAlertSkip(
                    matching_alert_id=result.matching_alert_id,
                    fingerprint=result.fingerprint,
                    pair=decision.pair,
                    direction=decision.direction,
                    timeframe=decision.timeframe,
                    alert_level=decision.level,
                    contributing_strategies=decision.contributing_strategies,
                    reason=result.reason,
                    skipped_at=evaluated_at,
                ),
            )
        return result


def alert_fingerprint(decision: AlertDecision) -> str:
    """Return a stable key for the decision's pair, direction, and setup."""
    if (
        decision.pair is None
        or decision.timeframe is None
        or decision.direction is None
        or decision.level is AlertLevel.NO_ALERT
        or not decision.contributing_strategies
    ):
        raise ValueError("Only complete alert decisions can be fingerprinted")

    payload = {
        "alert_level": decision.level.value,
        "direction": decision.direction.value,
        "pair": decision.pair.strip().upper(),
        "strategies": sorted(
            {strategy.strip().lower() for strategy in decision.contributing_strategies}
        ),
        "timeframe": decision.timeframe.strip().lower(),
    }
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return f"v1:{hashlib.sha256(serialized.encode()).hexdigest()}"
