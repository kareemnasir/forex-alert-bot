import os
import subprocess
import sys


def test_module_runs_in_dry_run_mode() -> None:
    environment = os.environ | {"DRY_RUN": "false"}

    result = subprocess.run(
        [sys.executable, "-m", "forex_alert_bot", "--dry-run"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0
    assert "Dry run enabled" in result.stderr


def test_module_does_not_run_alerts_when_dry_run_is_disabled() -> None:
    environment = os.environ | {"DRY_RUN": "false"}

    result = subprocess.run(
        [sys.executable, "-m", "forex_alert_bot"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0
    assert "signal checks are not implemented yet" in result.stderr
