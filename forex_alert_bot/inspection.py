"""Read-only SQLite queries and terminal reports for bot operators."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_TERMINAL_CONTROL_TRANSLATION = {
    codepoint: " " for codepoint in (*range(32), 127) if codepoint != 10
}


class InspectionError(RuntimeError):
    """Base error for a safe, read-only inspection failure."""


class DatabaseMissingError(InspectionError):
    """Raised when the configured runtime database does not exist."""


class RunNotFoundError(InspectionError):
    """Raised when an operator requests an unknown Run ID."""


class SQLiteInspector:
    """Read committed activity without initializing or migrating SQLite."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def recent_runs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return newest Runs with concise persisted-flow counts."""
        if limit <= 0:
            raise ValueError("Inspection limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    runs.id,
                    runs.status,
                    runs.dry_run,
                    runs.started_at,
                    runs.finished_at,
                    (SELECT COUNT(*) FROM candidate_signals WHERE run_id = runs.id),
                    (SELECT COUNT(*) FROM alert_decisions
                        WHERE run_id = runs.id AND stage = 'technical'),
                    (SELECT COUNT(*) FROM alert_decisions
                        WHERE run_id = runs.id AND stage = 'final'),
                    (SELECT COUNT(*) FROM alerts WHERE run_id = runs.id),
                    (SELECT COUNT(*) FROM errors WHERE run_id = runs.id)
                FROM runs
                ORDER BY runs.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "status": row[1],
                "dry_run": bool(row[2]),
                "started_at": row[3],
                "finished_at": row[4],
                "candidate_count": row[5],
                "technical_count": row[6],
                "final_count": row[7],
                "alert_count": row[8],
                "error_count": row[9],
            }
            for row in rows
        ]

    def run(self, run_id: int) -> dict[str, Any]:
        """Return the operator-safe persisted flow for one Run."""
        with self._connect() as connection:
            run = connection.execute(
                """
                SELECT id, status, dry_run, started_at, finished_at
                FROM runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise RunNotFoundError(f"Run {run_id} was not found.")
            return {
                "id": run[0],
                "status": run[1],
                "dry_run": bool(run[2]),
                "started_at": run[3],
                "finished_at": run[4],
                "errors": _rows(
                    connection,
                    """
                    SELECT stage, error_type, occurred_at
                    FROM errors WHERE run_id = ? ORDER BY stage, id
                    """,
                    run_id,
                ),
                "candidates": _rows(
                    connection,
                    """
                    SELECT id, strategy, pair, direction, timeframe
                    FROM candidate_signals WHERE run_id = ? ORDER BY id
                    """,
                    run_id,
                ),
                "news_analyses": _rows(
                    connection,
                    """
                    SELECT id, candidate_signal_id, status
                    FROM news_analyses WHERE run_id = ? ORDER BY id
                    """,
                    run_id,
                ),
                "technical_decisions": _rows(
                    connection,
                    """
                    SELECT id, pair, direction, timeframe, alert_level, score
                    FROM alert_decisions
                    WHERE run_id = ? AND stage = 'technical'
                    ORDER BY id
                    """,
                    run_id,
                ),
                "final_decisions": _rows(
                    connection,
                    """
                    SELECT id, pair, direction, timeframe, alert_level, score
                    FROM alert_decisions
                    WHERE run_id = ? AND stage = 'final'
                    ORDER BY id
                    """,
                    run_id,
                ),
                "adjustments": _rows(
                    connection,
                    """
                    SELECT technical_decision_id, final_decision_id,
                           technical_score, score_delta, final_score, reasons_json
                    FROM score_adjustments WHERE run_id = ? ORDER BY id
                    """,
                    run_id,
                ),
                "cooldown_skips": _rows(
                    connection,
                    """
                    SELECT matching_alert_id, pair, direction, timeframe,
                           alert_level, reason, skipped_at
                    FROM alert_skips WHERE run_id = ? ORDER BY id
                    """,
                    run_id,
                ),
                "delivery_skips": _rows(
                    connection,
                    """
                    SELECT alert_decision_id, skip_type, reason, skipped_at
                    FROM alert_delivery_skips WHERE run_id = ? ORDER BY id
                    """,
                    run_id,
                ),
                "alerts": _rows(
                    connection,
                    """
                    SELECT id, alert_decision_id, candidate_signal_id,
                           news_analysis_id, sent_at
                    FROM alerts WHERE run_id = ? ORDER BY id
                    """,
                    run_id,
                ),
            }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise DatabaseMissingError(f"Database does not exist: {self.path}")
        connection = None
        try:
            uri = f"{self.path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            connection.execute("PRAGMA query_only = ON")
            connection.execute("SELECT 1 FROM runs LIMIT 1")
            yield connection
        except sqlite3.DatabaseError:
            raise InspectionError("Database could not be inspected safely.") from None
        finally:
            if connection is not None:
                connection.close()


def format_recent_runs(runs: list[dict[str, Any]]) -> str:
    """Render a stable one-line summary for each recent Run."""
    if not runs:
        return "No recorded runs."
    lines = ["Recent runs"]
    for run in runs:
        lines.append(
            f"Run {run['id']} | {run['status']} | "
            f"dry-run={_yes_no(run['dry_run'])} | "
            f"started={run['started_at']} | finished={run['finished_at'] or '-'} | "
            f"candidates={run['candidate_count']} | technical={run['technical_count']} | "
            f"final={run['final_count']} | alerts={run['alert_count']} | "
            f"errors={run['error_count']}"
        )
    return _terminal_safe("\n".join(lines))


def format_run(report: dict[str, Any]) -> str:
    """Render one Run without provider payloads, messages, or credentials."""
    lines = [
        f"Run {report['id']}",
        f"Status: {report['status']}",
        f"Dry run: {_yes_no(report['dry_run'])}",
        f"Started: {report['started_at']}",
        f"Finished: {report['finished_at'] or '-'}",
    ]
    _section(
        lines,
        "Errors",
        report["errors"],
        lambda row: f"{row['stage']} | {row['error_type']} | occurred={row['occurred_at']}",
    )
    _section(
        lines,
        "Candidate Signals",
        report["candidates"],
        lambda row: (
            f"#{row['id']} | {row['strategy']} | {row['pair']} {row['direction']} | "
            f"{row['timeframe'] or '-'}"
        ),
    )
    _section(
        lines,
        "News Analyses",
        report["news_analyses"],
        lambda row: (
            f"#{row['id']} | {row['status']} | candidate={_reference(row['candidate_signal_id'])}"
        ),
    )
    _section(lines, "Technical Alert Decisions", report["technical_decisions"], _decision)
    _section(lines, "Final Alert Decisions", report["final_decisions"], _decision)
    _section(
        lines,
        "Score Adjustments",
        report["adjustments"],
        lambda row: (
            f"decision=#{row['technical_decision_id']} -> #{row['final_decision_id']} | "
            f"{row['technical_score']} -> {row['final_score']} "
            f"({row['score_delta']:+d}) | {_reasons(row['reasons_json'])}"
        ),
    )
    _section(
        lines,
        "Cooldown Skips",
        report["cooldown_skips"],
        lambda row: (
            f"{row['pair']} {row['direction']} | {row['alert_level']} | "
            f"{row['timeframe']} | matching-alert=#{row['matching_alert_id']} | {row['reason']}"
        ),
    )
    _section(
        lines,
        "Delivery Skips",
        report["delivery_skips"],
        lambda row: f"decision=#{row['alert_decision_id']} | {row['skip_type']} | {row['reason']}",
    )
    _section(
        lines,
        "Sent Alerts",
        report["alerts"],
        lambda row: (
            f"Alert #{row['id']} | decision={_reference(row['alert_decision_id'])} | "
            f"candidate=#{row['candidate_signal_id']} | news=#{row['news_analysis_id']} | "
            f"sent={row['sent_at']}"
        ),
    )
    return _terminal_safe("\n".join(lines))


def _rows(connection: sqlite3.Connection, query: str, run_id: int) -> list[dict[str, Any]]:
    cursor = connection.execute(query, (run_id,))
    columns = tuple(item[0] for item in cursor.description)
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _section(lines, title, rows, render) -> None:
    lines.extend(("", title))
    lines.extend((f"- {render(row)}" for row in rows))
    if not rows:
        lines.append("- none")


def _decision(row: dict[str, Any]) -> str:
    identity = " ".join(item for item in (row["pair"], row["direction"]) if item) or "No setup"
    return (
        f"#{row['id']} | {identity} | {row['alert_level']} | "
        f"score={row['score']} | {row['timeframe'] or '-'}"
    )


def _reference(value: int | None) -> str:
    return f"#{value}" if value is not None else "none"


def _reasons(value: str) -> str:
    try:
        reasons = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        raise InspectionError("Stored Run data could not be inspected safely.") from None
    if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
        raise InspectionError("Stored Run data could not be inspected safely.")
    return "; ".join(reasons) if reasons else "no adjustment reason"


def _yes_no(value: object) -> str:
    return "yes" if value else "no"


def _terminal_safe(value: str) -> str:
    return value.translate(_TERMINAL_CONTROL_TRANSLATION)
