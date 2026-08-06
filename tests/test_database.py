import sqlite3

import pytest

from forex_alert_bot.database import SQLiteLog


def test_database_initialization_creates_inspectable_tables(tmp_path) -> None:
    database_path = tmp_path / "logs" / "forex-alert-bot.sqlite3"

    database = SQLiteLog(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(errors)")}

    assert {"runs", "candidate_signals", "news_analyses", "alerts", "errors"} <= tables
    assert journal_mode == "wal"
    assert "errors_by_run_id" in indexes
    with database._connect() as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_run_lifecycle_records_successful_scheduled_run(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")

    run_id = database.start_run(dry_run=True)
    database.complete_run(run_id)

    run = database.get_run(run_id)

    assert run["id"] == run_id
    assert run["status"] == "completed"
    assert run["dry_run"] is True
    assert run["finished_at"] is not None


def test_failed_run_records_a_safe_error_record(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    run_id = database.start_run(dry_run=False)

    database.fail_run(run_id, stage="signal-check", error=ValueError("bad 'market' input"))

    assert database.get_run(run_id)["status"] == "failed"
    assert database.get_errors(run_id) == [
        {
            "run_id": run_id,
            "stage": "signal-check",
            "error_type": "ValueError",
            "message": "bad 'market' input",
        }
    ]


def test_alert_trace_links_run_candidate_and_news_input_output(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    run_id = database.start_run(dry_run=False)
    candidate_id = database.record_candidate_signal(
        run_id,
        strategy="trend-pullback",
        pair="EUR/USD",
        direction="BUY",
        timeframe="15m",
        payload={"technical_score": 71},
    )
    news_analysis_id = database.record_news_analysis(
        run_id,
        candidate_signal_id=candidate_id,
        input_payload={"headlines": ["EUR data improves"]},
        output_payload={"direction": "bullish", "strength": 0.55},
    )
    alert_id = database.record_alert(
        run_id,
        candidate_signal_id=candidate_id,
        news_analysis_id=news_analysis_id,
        message="EUR/USD BUY Watch",
    )

    assert database.get_alert_trace(alert_id) == {
        "run_id": run_id,
        "candidate": {
            "id": candidate_id,
            "strategy": "trend-pullback",
            "pair": "EUR/USD",
            "direction": "BUY",
            "timeframe": "15m",
            "payload": {"technical_score": 71},
        },
        "news_analysis": {
            "id": news_analysis_id,
            "input": {"headlines": ["EUR data improves"]},
            "output": {"direction": "bullish", "strength": 0.55},
            "status": "completed",
        },
        "message": "EUR/USD BUY Watch",
    }


def test_terminal_run_status_cannot_be_overwritten(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    completed_run_id = database.start_run(dry_run=False)
    failed_run_id = database.start_run(dry_run=False)
    database.complete_run(completed_run_id)
    database.fail_run(failed_run_id, stage="signal-check", error=RuntimeError("failed"))

    with pytest.raises(ValueError, match="started"):
        database.fail_run(completed_run_id, stage="signal-check", error=RuntimeError("failed"))
    with pytest.raises(ValueError, match="started"):
        database.complete_run(failed_run_id)


def test_cross_run_provenance_links_are_rejected(tmp_path) -> None:
    database = SQLiteLog(tmp_path / "forex-alert-bot.sqlite3")
    first_run_id = database.start_run(dry_run=False)
    second_run_id = database.start_run(dry_run=False)
    first_candidate_id = database.record_candidate_signal(
        first_run_id,
        strategy="trend-pullback",
        pair="EUR/USD",
        direction="BUY",
        timeframe="15m",
        payload={},
    )
    second_candidate_id = database.record_candidate_signal(
        second_run_id,
        strategy="breakout",
        pair="EUR/USD",
        direction="SELL",
        timeframe="15m",
        payload={},
    )
    second_first_run_candidate_id = database.record_candidate_signal(
        first_run_id,
        strategy="breakout",
        pair="EUR/USD",
        direction="SELL",
        timeframe="15m",
        payload={},
    )
    first_news_analysis_id = database.record_news_analysis(
        first_run_id,
        candidate_signal_id=first_candidate_id,
        input_payload={},
        output_payload={},
    )

    with pytest.raises(ValueError, match="candidate signal.*run"):
        database.record_news_analysis(
            second_run_id,
            candidate_signal_id=first_candidate_id,
            input_payload={},
            output_payload={},
        )
    with pytest.raises(ValueError, match="same run and candidate"):
        database.record_alert(
            second_run_id,
            candidate_signal_id=second_candidate_id,
            news_analysis_id=first_news_analysis_id,
            message="EUR/USD SELL Watch",
        )
    with pytest.raises(ValueError, match="same run and candidate"):
        database.record_alert(
            first_run_id,
            candidate_signal_id=second_first_run_candidate_id,
            news_analysis_id=first_news_analysis_id,
            message="EUR/USD SELL Watch",
        )
