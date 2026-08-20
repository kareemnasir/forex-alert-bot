import hashlib
import sqlite3
from datetime import UTC, datetime

from forex_alert_bot.config import Settings
from forex_alert_bot.cooldown import DuplicateAlertSkip
from forex_alert_bot.database import SQLiteLog
from forex_alert_bot.scoring import AlertLevel
from forex_alert_bot.strategies import SignalDirection

RECORDED_AT = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def test_recent_run_inspection_lists_status_timestamps_and_counts(
    monkeypatch, capsys, tmp_path
) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "forex-alert-bot.sqlite3"
    _record_inspectable_run(database_path)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-recent"]) == 0
    output = capsys.readouterr().out
    assert "Recent runs" in output
    assert "Run 1 | completed | dry-run=yes" in output
    assert "started=" in output
    assert "finished=" in output
    assert "candidates=1" in output
    assert "technical=1" in output
    assert "final=1" in output
    assert "alerts=1" in output
    assert "errors=1" in output


def test_specific_run_inspection_reports_complete_operator_flow(
    monkeypatch, capsys, tmp_path
) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "forex-alert-bot.sqlite3"
    _record_inspectable_run(database_path)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-run", "1"]) == 0
    output = capsys.readouterr().out
    assert "Run 1" in output
    assert "Status: completed" in output
    assert "Dry run: yes" in output
    assert "Errors" in output
    assert "news | RuntimeError | occurred=" in output
    assert "provider-secret-error" not in output
    assert "Candidate Signals" in output
    assert "breakout | EUR/USD BUY | 15min" in output
    assert "News Analyses" in output
    assert "available | candidate=#1" in output
    assert "Technical Alert Decisions" in output
    assert "EUR/USD BUY | Watch | score=68 | 15min" in output
    assert "Final Alert Decisions" in output
    assert "EUR/USD BUY | Watch | score=74 | 15min" in output
    assert "Score Adjustments" in output
    assert "68 -> 74 (+6)" in output
    assert "Cooldown Skips" in output
    assert "matching-alert=#1" in output
    assert "Delivery Skips" in output
    for skip_type in ("dry_run", "formatting", "delivery_unavailable", "delivery_error"):
        assert skip_type in output
    assert "Sent Alerts" in output
    assert "Alert #1 | decision=#2 | candidate=#1 | news=#1" in output
    assert "provider-secret-payload" not in output
    assert "formatted-secret-message" not in output


def test_missing_database_is_reported_without_creating_it(monkeypatch, capsys, tmp_path) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "missing.sqlite3"
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-recent"]) == 1
    output = capsys.readouterr()
    assert "Database does not exist" in output.err
    assert not database_path.exists()


def test_empty_database_has_useful_inspection_output(monkeypatch, capsys, tmp_path) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "empty.sqlite3"
    SQLiteLog(database_path)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-recent"]) == 0
    assert "No recorded runs." in capsys.readouterr().out


def test_unknown_run_id_is_reported_clearly(monkeypatch, capsys, tmp_path) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "forex-alert-bot.sqlite3"
    SQLiteLog(database_path)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-run", "999"]) == 1
    assert "Run 999 was not found." in capsys.readouterr().err


def test_inspection_does_not_change_database_bytes_or_metadata(
    monkeypatch, capsys, tmp_path
) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "forex-alert-bot.sqlite3"
    _record_inspectable_run(database_path)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )
    before = _snapshot(database_path)

    assert cli.main(["--inspect-recent"]) == 0
    assert cli.main(["--inspect-run", "1"]) == 0
    capsys.readouterr()

    assert _snapshot(database_path) == before


def test_incompatible_database_is_reported_without_a_traceback(
    monkeypatch, capsys, tmp_path
) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "incompatible.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                dry_run INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO runs (status, dry_run, started_at)
            VALUES ('completed', 1, '2026-08-20T15:00:00+00:00')
            """
        )
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-recent"]) == 1
    output = capsys.readouterr()
    assert "Database could not be inspected safely." in output.err
    assert "Traceback" not in output.err


def test_operator_output_neutralizes_terminal_control_characters(
    monkeypatch, capsys, tmp_path
) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "forex-alert-bot.sqlite3"
    _record_inspectable_run(database_path, adjustment_reason="News supports BUY.\x1b[31m")
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-run", "1"]) == 0
    output = capsys.readouterr().out
    assert "News supports BUY. [31m" in output
    assert "\x1b" not in output


def test_malformed_stored_run_shape_is_reported_safely(monkeypatch, capsys, tmp_path) -> None:
    from forex_alert_bot import cli

    database_path = tmp_path / "forex-alert-bot.sqlite3"
    _record_inspectable_run(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE score_adjustments SET reasons_json = '42'")
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(database_path=database_path),
    )

    assert cli.main(["--inspect-run", "1"]) == 1
    output = capsys.readouterr()
    assert "Stored Run data could not be inspected safely." in output.err
    assert "Traceback" not in output.err


def _record_inspectable_run(
    database_path,
    *,
    adjustment_reason: str = "News supports BUY.",
) -> None:
    database = SQLiteLog(database_path)
    run_id = database.start_run(dry_run=True)
    candidate_id = database.record_candidate_signal(
        run_id,
        strategy="breakout",
        pair="EUR/USD",
        direction="BUY",
        timeframe="15min",
        payload={"provider_payload": "provider-secret-payload"},
    )
    technical_id = database.record_alert_decision(
        run_id,
        stage="technical",
        pair="EUR/USD",
        direction="BUY",
        timeframe="15min",
        alert_level="Watch",
        score=68,
        news_analysis_id=None,
        payload={"candidate_ids": [candidate_id]},
    )
    news_id = database.record_news_analysis(
        run_id,
        candidate_signal_id=candidate_id,
        input_payload={"provider_payload": "provider-secret-payload"},
        output_payload={"raw_response": "provider-secret-payload"},
        status="available",
    )
    final_id = database.record_alert_decision(
        run_id,
        stage="final",
        pair="EUR/USD",
        direction="BUY",
        timeframe="15min",
        alert_level="Watch",
        score=74,
        news_analysis_id=news_id,
        payload={"candidate_ids": [candidate_id]},
    )
    database.record_score_adjustment(
        run_id,
        technical_decision_id=technical_id,
        final_decision_id=final_id,
        news_analysis_id=news_id,
        technical_score=68,
        score_delta=6,
        final_score=74,
        reasons=(adjustment_reason,),
    )
    alert_id = database.record_alert(
        run_id,
        candidate_signal_id=candidate_id,
        news_analysis_id=news_id,
        alert_decision_id=final_id,
        fingerprint="v1:operator-test",
        message="formatted-secret-message",
        sent_at=RECORDED_AT,
    )
    database.record_alert_skip(
        run_id,
        DuplicateAlertSkip(
            matching_alert_id=alert_id,
            fingerprint="v1:operator-test",
            pair="EUR/USD",
            direction=SignalDirection.BUY,
            timeframe="15min",
            alert_level=AlertLevel.WATCH,
            contributing_strategies=("breakout",),
            reason="Matching alert is in cooldown.",
            skipped_at=RECORDED_AT,
        ),
    )
    for skip_type in ("dry_run", "formatting", "delivery_unavailable", "delivery_error"):
        database.record_alert_delivery_skip(
            run_id,
            alert_decision_id=final_id,
            skip_type=skip_type,
            reason=f"Recorded {skip_type} skip.",
            fingerprint="v1:operator-test",
            message="formatted-secret-message",
            skipped_at=RECORDED_AT,
        )
    database.record_error(
        run_id,
        stage="news",
        error=RuntimeError("provider-secret-error"),
    )
    database.complete_run(run_id)


def _snapshot(database_path) -> tuple[int, int, int, int, str]:
    metadata = database_path.stat()
    return (
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_ino,
        hashlib.sha256(database_path.read_bytes()).hexdigest(),
    )
