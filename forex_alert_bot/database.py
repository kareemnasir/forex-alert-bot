"""SQLite persistence for inspectable Forex alert-bot runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from forex_alert_bot.cooldown import AlertHistoryEntry, DuplicateAlertSkip


class SQLiteLog:
    """Initialize and write the application's local SQLite event log."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidate_signals (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES runs(id),
                    strategy TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    timeframe TEXT,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS news_analyses (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES runs(id),
                    candidate_signal_id INTEGER REFERENCES candidate_signals(id),
                    input_json TEXT NOT NULL,
                    output_json TEXT,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES runs(id),
                    candidate_signal_id INTEGER NOT NULL REFERENCES candidate_signals(id),
                    news_analysis_id INTEGER NOT NULL REFERENCES news_analyses(id),
                    fingerprint TEXT NOT NULL,
                    message TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER REFERENCES runs(id),
                    stage TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alert_skips (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES runs(id),
                    matching_alert_id INTEGER NOT NULL REFERENCES alerts(id),
                    fingerprint TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    alert_level TEXT NOT NULL,
                    contributing_strategies_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    skipped_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS errors_by_run_id ON errors (run_id, id);
                CREATE INDEX IF NOT EXISTS alert_skips_by_run_id ON alert_skips (run_id, id);
                """
            )
            alert_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(alerts)").fetchall()
            }
            if "fingerprint" not in alert_columns:
                connection.execute("ALTER TABLE alerts ADD COLUMN fingerprint TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS alerts_by_fingerprint_sent_at
                ON alerts (fingerprint, sent_at)
                """
            )

    def start_run(self, *, dry_run: bool) -> int:
        """Create a scheduled-run record and return its identifier."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO runs (started_at, status, dry_run) VALUES (?, ?, ?)",
                (_timestamp(), "started", dry_run),
            )
        return cursor.lastrowid

    def complete_run(self, run_id: int) -> None:
        """Mark a run as completed."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ? AND status = ?",
                ("completed", _timestamp(), run_id, "started"),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only a started run can be completed")

    def fail_run(self, run_id: int, *, stage: str, error: Exception) -> None:
        """Mark a run failed and retain a safe, parameterized error record."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ? AND status = ?",
                ("failed", _timestamp(), run_id, "started"),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only a started run can be failed")
            connection.execute(
                """
                INSERT INTO errors (run_id, stage, error_type, message, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, stage, type(error).__name__, str(error), _timestamp()),
            )

    def record_error(self, run_id: int, *, stage: str, error: Exception) -> None:
        """Record a recoverable run error without changing the run outcome."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO errors (run_id, stage, error_type, message, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, stage, type(error).__name__, str(error), _timestamp()),
            )

    def get_run(self, run_id: int) -> dict[str, object]:
        """Return an inspectable run record."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, status, dry_run, finished_at FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"No run exists with id {run_id}")
        return {
            "id": row[0],
            "status": row[1],
            "dry_run": bool(row[2]),
            "finished_at": row[3],
        }

    def get_errors(self, run_id: int) -> list[dict[str, object]]:
        """Return error records for one run in creation order."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, stage, error_type, message
                FROM errors
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "stage": row[1],
                "error_type": row[2],
                "message": row[3],
            }
            for row in rows
        ]

    def record_candidate_signal(
        self,
        run_id: int,
        *,
        strategy: str,
        pair: str,
        direction: str,
        timeframe: str | None,
        payload: object,
    ) -> int:
        """Record a strategy candidate emitted by one run."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO candidate_signals
                    (run_id, strategy, pair, direction, timeframe, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, strategy, pair, direction, timeframe, _json(payload)),
            )
        return cursor.lastrowid

    def record_news_analysis(
        self,
        run_id: int,
        *,
        candidate_signal_id: int | None,
        input_payload: object,
        output_payload: object | None,
        status: str = "completed",
    ) -> int:
        """Record the exact input and output of a news-analysis attempt."""
        with self._connect() as connection:
            if candidate_signal_id is not None:
                candidate_run = connection.execute(
                    "SELECT run_id FROM candidate_signals WHERE id = ?", (candidate_signal_id,)
                ).fetchone()
                if candidate_run is None or candidate_run[0] != run_id:
                    raise ValueError("The candidate signal must belong to the news analysis run")
            cursor = connection.execute(
                """
                INSERT INTO news_analyses
                    (run_id, candidate_signal_id, input_json, output_json, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    candidate_signal_id,
                    _json(input_payload),
                    _json(output_payload) if output_payload is not None else None,
                    status,
                ),
            )
        return cursor.lastrowid

    def record_alert(
        self,
        run_id: int,
        *,
        candidate_signal_id: int,
        news_analysis_id: int,
        message: str,
        fingerprint: str,
        sent_at: datetime | None = None,
    ) -> int:
        """Record one sent alert with its candidate and news-analysis links."""
        with self._connect() as connection:
            provenance = connection.execute(
                """
                SELECT
                    candidate_signals.run_id,
                    news_analyses.run_id,
                    news_analyses.candidate_signal_id
                FROM candidate_signals
                JOIN news_analyses ON news_analyses.id = ?
                WHERE candidate_signals.id = ?
                """,
                (news_analysis_id, candidate_signal_id),
            ).fetchone()
            if provenance != (run_id, run_id, candidate_signal_id):
                raise ValueError("Alert links must belong to the same run and candidate signal")
            cursor = connection.execute(
                """
                INSERT INTO alerts
                    (run_id, candidate_signal_id, news_analysis_id, fingerprint, message, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    candidate_signal_id,
                    news_analysis_id,
                    fingerprint,
                    message,
                    _timestamp(sent_at),
                ),
            )
        return cursor.lastrowid

    def get_recent_alerts(
        self,
        *,
        fingerprint: str,
        since: datetime,
        until: datetime,
    ) -> tuple[AlertHistoryEntry, ...]:
        """Return the newest matching alert inside the requested history bounds."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, fingerprint, sent_at
                FROM alerts
                WHERE fingerprint = ? AND sent_at > ? AND sent_at <= ?
                ORDER BY sent_at DESC, id DESC
                LIMIT 1
                """,
                (fingerprint, _timestamp(since), _timestamp(until)),
            ).fetchall()
        return tuple(
            AlertHistoryEntry(
                alert_id=row[0],
                fingerprint=row[1],
                sent_at=datetime.fromisoformat(row[2]),
            )
            for row in rows
        )

    def record_alert_skip(self, run_id: int, skip: DuplicateAlertSkip) -> int:
        """Record a duplicate alert rejected by the cooldown service."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO alert_skips (
                    run_id,
                    matching_alert_id,
                    fingerprint,
                    pair,
                    direction,
                    timeframe,
                    alert_level,
                    contributing_strategies_json,
                    reason,
                    skipped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    skip.matching_alert_id,
                    skip.fingerprint,
                    skip.pair,
                    skip.direction.value,
                    skip.timeframe,
                    skip.alert_level.value,
                    _json(skip.contributing_strategies),
                    skip.reason,
                    _timestamp(skip.skipped_at),
                ),
            )
        return cursor.lastrowid

    def get_alert_skips(self, run_id: int) -> list[dict[str, object]]:
        """Return duplicate skips for one run in creation order."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    run_id,
                    matching_alert_id,
                    fingerprint,
                    pair,
                    direction,
                    timeframe,
                    alert_level,
                    contributing_strategies_json,
                    reason,
                    skipped_at
                FROM alert_skips
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "run_id": row[0],
                "matching_alert_id": row[1],
                "fingerprint": row[2],
                "pair": row[3],
                "direction": row[4],
                "timeframe": row[5],
                "alert_level": row[6],
                "contributing_strategies": json.loads(row[7]),
                "reason": row[8],
                "skipped_at": row[9],
            }
            for row in rows
        ]

    def get_alert_trace(self, alert_id: int) -> dict[str, object]:
        """Return the candidate and news input/output behind a sent alert."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    alerts.run_id,
                    candidate_signals.id,
                    candidate_signals.strategy,
                    candidate_signals.pair,
                    candidate_signals.direction,
                    candidate_signals.timeframe,
                    candidate_signals.payload_json,
                    news_analyses.id,
                    news_analyses.input_json,
                    news_analyses.output_json,
                    news_analyses.status,
                    alerts.fingerprint,
                    alerts.message
                FROM alerts
                JOIN candidate_signals ON candidate_signals.id = alerts.candidate_signal_id
                JOIN news_analyses ON news_analyses.id = alerts.news_analysis_id
                WHERE alerts.id = ?
                """,
                (alert_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"No alert exists with id {alert_id}")
        return {
            "run_id": row[0],
            "candidate": {
                "id": row[1],
                "strategy": row[2],
                "pair": row[3],
                "direction": row[4],
                "timeframe": row[5],
                "payload": json.loads(row[6]),
            },
            "news_analysis": {
                "id": row[7],
                "input": json.loads(row[8]),
                "output": json.loads(row[9]) if row[9] is not None else None,
                "status": row[10],
            },
            "fingerprint": row[11],
            "message": row[12],
        }


def _timestamp(value: datetime | None = None) -> str:
    timestamp = datetime.now(UTC) if value is None else value
    if timestamp.utcoffset() is None:
        raise ValueError("timestamps must include timezone information")
    return timestamp.astimezone(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
