from configparser import ConfigParser
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_UNIT = REPOSITORY_ROOT / "deploy" / "forex-alert-bot.service"
DEPLOYMENT_GUIDE = REPOSITORY_ROOT / "docs" / "vps-deployment.md"
PROJECT_CONTEXT = REPOSITORY_ROOT / "docs" / "project-context.md"
RUNTIME_LOCK = REPOSITORY_ROOT / "requirements.lock"
BUILD_LOCK = REPOSITORY_ROOT / "requirements-build.lock"


def read_service_unit() -> ConfigParser:
    unit = ConfigParser(interpolation=None, strict=True)
    with SERVICE_UNIT.open(encoding="utf-8") as service_file:
        unit.read_file(service_file)
    return unit


def guide_section(guide: str, heading: str, next_heading: str) -> str:
    return guide[guide.index(heading) : guide.index(next_heading)]


def test_systemd_unit_enforces_the_vps_runtime_contract() -> None:
    unit = read_service_unit()
    unit_config = unit["Unit"]
    service = unit["Service"]

    assert unit_config["After"] == "network-online.target"
    assert unit_config["Wants"] == "network-online.target"
    assert int(unit_config["StartLimitIntervalSec"]) > 0
    assert int(unit_config["StartLimitBurst"]) > 0
    assert service["User"] == "forex-alert-bot"
    assert service["Group"] == "forex-alert-bot"
    assert service["WorkingDirectory"] == "/opt/forex-alert-bot"
    assert service["EnvironmentFile"] == "/etc/forex-alert-bot/forex-alert-bot.env"
    assert service["ExecStart"] == (
        "/opt/forex-alert-bot/.venv/bin/python -m forex_alert_bot --schedule --dry-run"
    )
    assert service["Restart"] == "on-failure"
    assert service["RestartSec"]
    assert service["StandardOutput"] == "journal"
    assert service["StandardError"] == "journal"
    assert service["UMask"] == "0027"
    assert service["NoNewPrivileges"] == "true"
    assert service["PrivateTmp"] == "true"
    assert service["ProtectSystem"] == "strict"
    assert service["ProtectHome"] == "true"
    assert service["ReadWritePaths"] == "/var/lib/forex-alert-bot"
    assert service["KillSignal"] == "SIGTERM"
    assert service["TimeoutStopSec"] == "300s"

    serialized_unit = SERVICE_UNIT.read_text(encoding="utf-8")
    for secret_name in (
        "MARKET_DATA_API_KEY",
        "NEWS_API_KEY",
        "OLLAMA_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        assert secret_name not in serialized_unit


def test_vps_guide_covers_safe_installation_and_recovery_commands() -> None:
    guide = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")

    assert "Debian 13 on DigitalOcean" in guide
    assert "Do not set `DRY_RUN=false`" in guide
    assert "DRY_RUN=true" in guide
    for required_setting in (
        "MARKET_DATA_API_KEY=<MARKET_DATA_API_KEY>",
        "NEWS_API_KEY=<NEWS_API_KEY>",
        "OLLAMA_API_KEY=<OLLAMA_API_KEY>",
        "OLLAMA_MODEL=<OLLAMA_MODEL>",
    ):
        assert required_setting in guide
    for path in (
        "/opt/forex-alert-bot",
        "/etc/forex-alert-bot/forex-alert-bot.env",
        "/var/lib/forex-alert-bot/forex-alert-bot.sqlite3",
        "/var/backups/forex-alert-bot",
    ):
        assert path in guide
    for command in (
        "python -m forex_alert_bot --run-once --dry-run",
        "python -m forex_alert_bot --inspect-recent",
        "python -m forex_alert_bot --inspect-run",
        "systemctl daemon-reload",
        "systemctl enable forex-alert-bot.service",
        "journalctl -u forex-alert-bot.service",
        "systemd-analyze verify",
    ):
        assert command in guide
    assert "chmod 0640" in guide
    assert ".backup" in guide
    assert "PRAGMA integrity_check;" in guide
    assert "PRAGMA foreign_key_check;" in guide
    assert ".restore" in guide
    assert guide.index("systemctl stop forex-alert-bot.service") < guide.index(".restore")

    backup = guide_section(guide, "## 8. Back up SQLite safely", "## 9. Restore SQLite safely")
    restore = guide_section(guide, "## 9. Restore SQLite safely", "## 10. Update the application")
    update = guide_section(guide, "## 10. Update the application", "## 11. Roll back code")
    rollback = guide_section(guide, "## 11. Roll back code", "## 12. Gate for issue #32")
    for fail_fast_section in (backup, restore, update, rollback):
        assert "set -euo pipefail" in fail_fast_section
    assert 'test -f "$RESTORE_SOURCE"' in restore
    assert 'test -s "$RESTORE_SOURCE"' in restore
    assert 'sqlite3 -readonly "$RESTORE_SOURCE"' in restore
    assert "name='runs'" in restore
    for inactive_verification in (update, rollback):
        assert "cd /opt/forex-alert-bot" in inactive_verification
        assert inactive_verification.index("--run-once --dry-run") < inactive_verification.index(
            "systemctl start forex-alert-bot.service"
        )


def test_project_context_uses_the_canonical_weekday_scheduler() -> None:
    project_context = PROJECT_CONTEXT.read_text(encoding="utf-8")

    assert "create_scheduler(settings)" in project_context
    assert 'trigger="cron"' not in project_context


def test_vps_install_uses_a_hash_locked_runtime_dependency_graph() -> None:
    guide = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")
    runtime_lock = RUNTIME_LOCK.read_text(encoding="utf-8")
    build_lock = BUILD_LOCK.read_text(encoding="utf-8")
    locked_requirements = [
        line for line in runtime_lock.splitlines() if line and not line.startswith((" ", "#"))
    ]

    assert len(locked_requirements) > 8
    assert all("==" in requirement for requirement in locked_requirements)
    assert "--hash=sha256:" in runtime_lock
    assert "setuptools==" in build_lock
    assert "wheel==" in build_lock
    assert "--hash=sha256:" in build_lock
    assert guide.count("--require-hashes") == 6
    assert guide.count("--no-build-isolation") >= 3
    assert guide.count("-r /opt/forex-alert-bot/requirements-build.lock") == 3
    assert guide.count("-r /opt/forex-alert-bot/requirements.lock") == 3
