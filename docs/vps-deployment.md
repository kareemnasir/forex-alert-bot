# Ubuntu VPS deployment

This is the authoritative V1 runbook for installing the Forex Alert Bot as one Python service on
Ubuntu 24.04 LTS. It assumes an operator with `sudo` access and an intended application revision
identified by its full Git commit SHA.

> **Safety gate:** Do not set `DRY_RUN=false`, remove the unit's `--dry-run` argument, or send a
> Telegram test message during this deployment. Live delivery remains disabled until issue #32 is
> completed and reviewed.

The service has no inbound application port. Do not add a firewall rule for it. It makes outbound
DNS and HTTPS requests to the configured providers and Telegram.

## Supported host and layout

Use Ubuntu 24.04 LTS with Python 3.12 or newer. The fixed V1 layout is:

| Concern | Path | Runtime owner |
| --- | --- | --- |
| Source and virtual environment | `/opt/forex-alert-bot` | `root:forex-alert-bot` |
| External environment file | `/etc/forex-alert-bot/forex-alert-bot.env` | `root:forex-alert-bot` |
| Persistent data directory | `/var/lib/forex-alert-bot` | `forex-alert-bot:forex-alert-bot` |
| SQLite database | `/var/lib/forex-alert-bot/forex-alert-bot.sqlite3` | `forex-alert-bot:forex-alert-bot` |
| Operator-managed backups | `/var/backups/forex-alert-bot` | `root:forex-alert-bot` |

The source tree is replaceable. The environment file, database, and backups are external to it and
must not be removed during an install, update, or rollback.

## 1. Install host packages

```bash
sudo apt update
sudo apt install --yes ca-certificates git python3 python3-venv sqlite3
python3 --version
```

Confirm the displayed Python version is at least 3.12.

## 2. Create the service identity and directories

```bash
sudo adduser --system --group --home /opt/forex-alert-bot \
  --no-create-home --shell /usr/sbin/nologin forex-alert-bot
sudo install -d -o root -g forex-alert-bot -m 0750 /opt/forex-alert-bot
sudo install -d -o root -g forex-alert-bot -m 0750 /etc/forex-alert-bot
sudo install -d -o forex-alert-bot -g forex-alert-bot -m 0750 /var/lib/forex-alert-bot
sudo install -d -o root -g forex-alert-bot -m 0750 /var/backups/forex-alert-bot
```

`forex-alert-bot` has no interactive shell and owns only runtime state. Root owns source,
dependencies, configuration, and backups.

## 3. Install the intended application revision

Replace `<APP_REVISION>` with a reviewed full commit SHA. Never put a GitHub token in the clone URL
or shell history; arrange repository access through an approved credential mechanism when the
repository is private.

```bash
sudo git clone https://github.com/kareemnasir/forex-alert-bot.git /opt/forex-alert-bot
sudo git -C /opt/forex-alert-bot fetch --prune origin
sudo git -C /opt/forex-alert-bot checkout --detach <APP_REVISION>
sudo chown -R root:forex-alert-bot /opt/forex-alert-bot
sudo chmod -R u=rwX,g=rX,o= /opt/forex-alert-bot
sudo python3 -m venv /opt/forex-alert-bot/.venv
sudo /opt/forex-alert-bot/.venv/bin/python -m pip install --require-hashes \
  -r /opt/forex-alert-bot/requirements-build.lock
sudo /opt/forex-alert-bot/.venv/bin/python -m pip install --require-hashes \
  --no-build-isolation \
  -r /opt/forex-alert-bot/requirements.lock
sudo /opt/forex-alert-bot/.venv/bin/python -m pip check
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --help
'
```

`requirements.txt` is the human-maintained runtime input. `requirements-build.txt` lists the tools
needed to build the one source-only runtime package. Their corresponding `.lock` files are Python
3.12 universal, fully pinned transitive graphs used by every production install. The first install
loads only hash-locked build tools. The runtime install uses `--no-build-isolation`, so pip cannot
resolve an unreviewed build environment. Do not upgrade pip or resolve either input file on the VPS.
When dependencies change, regenerate and review both locks on a developer machine:

```bash
uv pip compile --python-version 3.12 --universal --generate-hashes \
  requirements.txt -o requirements.lock
uv pip compile --python-version 3.12 --universal --generate-hashes \
  requirements-build.txt -o requirements-build.lock
```

`requirements-dev.txt` contains Pytest and Ruff for CI, a developer workstation, or a disposable
verification environment; the service does not need those packages to start. Before deployment,
the selected revision must pass:

```bash
python -m pytest
ruff check .
ruff format --check .
```

## 4. Create external configuration

The repository's `.env.example` is the single canonical configuration inventory. Copy every
assignment from it into the external file, then replace placeholders there. Do not create a
production `.env` inside `/opt/forex-alert-bot`, pass secrets on the command line, or commit the
external file.

```bash
sudo install -o root -g forex-alert-bot -m 0640 /dev/null \
  /etc/forex-alert-bot/forex-alert-bot.env
sudoedit /etc/forex-alert-bot/forex-alert-bot.env
sudo chown root:forex-alert-bot /etc/forex-alert-bot/forex-alert-bot.env
sudo chmod 0640 /etc/forex-alert-bot/forex-alert-bot.env
sudo ln -s /etc/forex-alert-bot/forex-alert-bot.env /opt/forex-alert-bot/.env
```

The following provider settings are required for a complete provider-backed Run. Replace every
placeholder before starting the service. Telegram settings are optional while delivery remains in
dry-run mode. Retain all other entries from `.env.example`, and set these values exactly:

```dotenv
MARKET_DATA_API_KEY=<MARKET_DATA_API_KEY>
NEWS_API_KEY=<NEWS_API_KEY>
OLLAMA_API_KEY=<OLLAMA_API_KEY>
OLLAMA_MODEL=<OLLAMA_MODEL>
DATABASE_PATH=/var/lib/forex-alert-bot/forex-alert-bot.sqlite3
DRY_RUN=true
APP_TIMEZONE=America/Detroit
```

Use clear placeholders such as `<MARKET_DATA_API_KEY>` only while editing; replace them before
starting the service. Telegram credentials may be stored for the later issue #32 review, but dry-run
does not use them. The service user can read the file through its group; unrelated users cannot.
The ignored `/opt/forex-alert-bot/.env` symlink contains no values; it lets manual CLI commands use
the application's existing dotenv loader while the actual configuration remains under `/etc`.
The systemd unit reads that same external file directly. Explicit process environment variables
still take precedence over file values, matching the application's existing configuration behavior.

Check metadata without printing configuration values:

```bash
sudo stat -c '%U %G %a %n' /etc/forex-alert-bot/forex-alert-bot.env
sudo -u forex-alert-bot test -r /etc/forex-alert-bot/forex-alert-bot.env
```

Expected metadata is `root forex-alert-bot 640`.

## 5. Run one safe preflight Run

The real application CLI forms used below are:

```bash
python -m forex_alert_bot --run-once --dry-run
python -m forex_alert_bot --inspect-recent
python -m forex_alert_bot --inspect-run <RUN_ID>
python -m forex_alert_bot --schedule --dry-run
```

Run the one-shot command as the service user. The process follows the protected `.env` symlink; no
secret value appears in the command or shell history:

```bash
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --run-once --dry-run
'
```

Record the printed Run ID. Inspect it through the read-only operator CLI, replacing `<RUN_ID>`:

```bash
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --inspect-recent
'
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --inspect-run "$1"
' bash <RUN_ID>
```

Require `Status: completed`, `Dry run: yes`, and no sent Alert. A qualifying final decision should
show a `dry_run` delivery skip. Provider or sentiment problems may leave the Run completed but add
Error Records; investigate them before starting recurring execution.

## 6. Install and validate the systemd unit

The checked-in unit forces `--dry-run` in addition to `DRY_RUN=true`, runs as the dedicated user,
bounds repeated failures, and gives the process write access only to the data directory.

```bash
sudo install -o root -g root -m 0644 \
  /opt/forex-alert-bot/deploy/forex-alert-bot.service \
  /etc/systemd/system/forex-alert-bot.service
sudo systemd-analyze verify /etc/systemd/system/forex-alert-bot.service
sudo systemctl daemon-reload
sudo systemctl enable forex-alert-bot.service
sudo systemctl start forex-alert-bot.service
```

`systemd-analyze verify` must run on the Ubuntu target. Static repository tests on another operating
system do not prove that systemd loaded the unit.

## 7. Operate and observe the service

```bash
sudo systemctl status forex-alert-bot.service --no-pager
sudo systemctl stop forex-alert-bot.service
sudo systemctl start forex-alert-bot.service
sudo systemctl restart forex-alert-bot.service
sudo journalctl -u forex-alert-bot.service --since today --no-pager
sudo journalctl -u forex-alert-bot.service -f
```

The application handles systemd's `SIGTERM` by waiting for an in-progress signal check to finish,
bounded by the unit's 300-second stop timeout. That budget covers the current default sequential
provider request ceiling (up to 120 seconds of market-data attempts, 10 seconds for news, and 60
seconds of sentiment attempts) with margin for computation and SQLite. Recalculate and, if needed,
raise `TimeoutStopSec` before increasing the pair/timeframe inventory, request timeouts, or retry
counts. Starting an already-active unit does not create a duplicate process. APScheduler also limits
the signal-check job to one concurrent instance.

### V1 weekday policy

All fire times use `APP_TIMEZONE` and remain inside the configured alert window:

- Sunday: 17:00 through the configured end hour.
- Monday through Thursday: the configured start hour through the configured end hour.
- Friday: the configured start hour through 17:00.
- Saturday: no Runs.

The default remains `America/Detroit`, 07:00–22:00, at `:00` and `:30` with the final end-hour Run
at `:00`. This approximates the normal Sunday-evening-to-Friday-evening Forex week. It does not
model holidays, exceptional closures, or broker-specific sessions; V1 has no market calendar.

### Verify a scheduled Run

After a configured fire time has passed, do not infer success only from `active (running)`:

1. Check `journalctl -u forex-alert-bot.service` for a signal-check start.
2. Run `--inspect-recent` and identify a new Run created after service start.
3. Run `--inspect-run <RUN_ID>` and require `completed`, `Dry run: yes`, and zero sent Alerts.
4. Review every Error Record and delivery skip.

These steps remain pending until they are performed on an explicitly authorized VPS. Repository
verification is not live service evidence.

### Recognize failures

- Configuration error: the process exits before scheduling; `systemctl status` and journald show a
  configuration exception. Correct the external file, then use `systemctl reset-failed` and start.
- Market-data provider: the Run normally completes with a `market-data` Error Record and no usable
  candidate for the affected fetch. Check credentials, provider status, and rate limits.
- News provider: inspect a `news` Error Record and an unavailable News Analysis.
- Sentiment provider: inspect a `sentiment` Error Record and unavailable sentiment; confirm Ollama
  host, model, key, and provider status.
- Telegram: initial dry-run must show a `dry_run` delivery skip, not a sent Alert. Telegram errors
  are not expected because delivery is suppressed. Do not use `--telegram-test` during issue #30.
- Persistent startup failure: the unit stops retrying after its configured start-limit burst. Fix
  the cause, then run `sudo systemctl reset-failed forex-alert-bot.service` before starting again.

## 8. Back up SQLite safely

SQLite runs in WAL mode, so never copy only the live main database file. Use SQLite's supported
online backup command. This does not require stopping the service.

```bash
(
set -euo pipefail
DATABASE_PATH=/var/lib/forex-alert-bot/forex-alert-bot.sqlite3
BACKUP_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="/var/backups/forex-alert-bot/forex-alert-bot-${BACKUP_TIMESTAMP}.sqlite3"
sudo test -f "$DATABASE_PATH"
sudo test -s "$DATABASE_PATH"
sudo test ! -e "$BACKUP_PATH"
sudo sqlite3 "$DATABASE_PATH" ".backup '$BACKUP_PATH'"
test "$(sudo sqlite3 -readonly "$BACKUP_PATH" 'PRAGMA integrity_check;')" = "ok"
test -z "$(sudo sqlite3 -readonly "$BACKUP_PATH" 'PRAGMA foreign_key_check;')"
sudo chown root:forex-alert-bot "$BACKUP_PATH"
sudo chmod 0640 "$BACKUP_PATH"
sudo stat -c '%U %G %a %s %n' "$BACKUP_PATH"
)
```

`PRAGMA integrity_check;` must print exactly `ok`. `PRAGMA foreign_key_check;` must print no rows.
Do not label the backup usable until both conditions hold. The timestamped path prevents accidental
overwrite; V1 intentionally has no automated retention service.

## 9. Restore SQLite safely

Restore only for loss, corruption, or a proven data-compatibility problem. An ordinary code rollback
preserves the current database. Replace `<ABSOLUTE_BACKUP_PATH>` with a previously validated file.

Validate the source before stopping anything:

```bash
RESTORE_SOURCE=<ABSOLUTE_BACKUP_PATH>
(
set -euo pipefail
sudo test -f "$RESTORE_SOURCE"
sudo test -s "$RESTORE_SOURCE"
test "$(sudo sqlite3 -readonly "$RESTORE_SOURCE" 'PRAGMA integrity_check;')" = "ok"
test -z "$(sudo sqlite3 -readonly "$RESTORE_SOURCE" 'PRAGMA foreign_key_check;')"
test "$(sudo sqlite3 -readonly "$RESTORE_SOURCE" \
  "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='runs';")" = "1"
)
```

Then stop the service before `.restore`, preserve a logical snapshot and the exact old database/WAL
state, build and validate a replacement in the data directory, and move it into place:

```bash
(
set -euo pipefail
sudo systemctl stop forex-alert-bot.service
sudo systemctl is-active --quiet forex-alert-bot.service && exit 1 || true

DATABASE_PATH=/var/lib/forex-alert-bot/forex-alert-bot.sqlite3
RESTORE_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK_DIR="/var/backups/forex-alert-bot/pre-restore-${RESTORE_TIMESTAMP}"
RESTORED_DB="/var/lib/forex-alert-bot/.restore-${RESTORE_TIMESTAMP}.sqlite3"
sudo test ! -e "$ROLLBACK_DIR"
sudo test ! -e "$RESTORED_DB"
sudo install -d -o root -g forex-alert-bot -m 0750 "$ROLLBACK_DIR"
sudo sqlite3 "$DATABASE_PATH" ".backup '$ROLLBACK_DIR/pre-restore.sqlite3'"
sudo sqlite3 "$RESTORED_DB" ".restore '$RESTORE_SOURCE'"
test "$(sudo sqlite3 "$RESTORED_DB" 'PRAGMA integrity_check;')" = "ok"
test -z "$(sudo sqlite3 "$RESTORED_DB" 'PRAGMA foreign_key_check;')"
sudo install -d -o root -g root -m 0700 "$ROLLBACK_DIR/raw"
sudo mv "$DATABASE_PATH" "$ROLLBACK_DIR/raw/forex-alert-bot.sqlite3"
if sudo test -e "${DATABASE_PATH}-wal"; then
  sudo mv "${DATABASE_PATH}-wal" "$ROLLBACK_DIR/raw/forex-alert-bot.sqlite3-wal"
fi
if sudo test -e "${DATABASE_PATH}-shm"; then
  sudo mv "${DATABASE_PATH}-shm" "$ROLLBACK_DIR/raw/forex-alert-bot.sqlite3-shm"
fi
sudo chown forex-alert-bot:forex-alert-bot "$RESTORED_DB"
sudo chmod 0640 "$RESTORED_DB"
sudo mv "$RESTORED_DB" "$DATABASE_PATH"
sudo chown root:forex-alert-bot "$ROLLBACK_DIR/pre-restore.sqlite3"
sudo chmod 0640 "$ROLLBACK_DIR/pre-restore.sqlite3"
sudo systemctl start forex-alert-bot.service
sudo systemctl status forex-alert-bot.service --no-pager
)
```

Finally inspect journald, run `--inspect-recent`, and open a known Run with `--inspect-run`. If
verification fails, stop the service and recover from the timestamped pre-restore snapshot or the
raw main/WAL/SHM set kept together in `ROLLBACK_DIR`.

## 10. Update the application

Replace `<TARGET_REVISION>` with the reviewed full commit SHA. Record `PREVIOUS_REVISION` outside
the shell session before proceeding. This workflow stops the service so code and dependencies
cannot change beneath a running process; the database remains external and untouched.

```bash
(
set -euo pipefail
PREVIOUS_REVISION="$(sudo git -C /opt/forex-alert-bot rev-parse HEAD)"
TARGET_REVISION=<TARGET_REVISION>
UPDATE_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PREVIOUS_VENV="/opt/forex-alert-bot/.venv.previous-${UPDATE_TIMESTAMP}"
printf 'Previous revision: %s\nTarget revision: %s\n' "$PREVIOUS_REVISION" "$TARGET_REVISION"
sudo systemctl stop forex-alert-bot.service
sudo git -C /opt/forex-alert-bot fetch --prune origin
sudo git -C /opt/forex-alert-bot checkout --detach "$TARGET_REVISION"
sudo test ! -e /opt/forex-alert-bot/.venv.next
sudo test ! -e "$PREVIOUS_VENV"
sudo python3 -m venv /opt/forex-alert-bot/.venv.next
sudo /opt/forex-alert-bot/.venv.next/bin/python -m pip install --require-hashes \
  -r /opt/forex-alert-bot/requirements-build.lock
sudo /opt/forex-alert-bot/.venv.next/bin/python -m pip install --require-hashes \
  --no-build-isolation \
  -r /opt/forex-alert-bot/requirements.lock
sudo /opt/forex-alert-bot/.venv.next/bin/python -m pip check
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv.next/bin/python -m forex_alert_bot --help
'
sudo mv /opt/forex-alert-bot/.venv "$PREVIOUS_VENV"
sudo mv /opt/forex-alert-bot/.venv.next /opt/forex-alert-bot/.venv
sudo chown -R root:forex-alert-bot /opt/forex-alert-bot
sudo chmod -R u=rwX,g=rX,o= /opt/forex-alert-bot
sudo install -o root -g root -m 0644 \
  /opt/forex-alert-bot/deploy/forex-alert-bot.service \
  /etc/systemd/system/forex-alert-bot.service
sudo systemd-analyze verify /etc/systemd/system/forex-alert-bot.service
sudo systemctl daemon-reload
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --run-once --dry-run
'
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --inspect-recent
'
sudo systemctl start forex-alert-bot.service
sudo systemctl status forex-alert-bot.service --no-pager
sudo journalctl -u forex-alert-bot.service --since '-10 minutes' --no-pager
)
```

The block runs and inspects a one-shot dry-run while the scheduler is stopped, then starts the
service. Inspect journald and the new scheduled Run before considering the update complete. Record
the printed `PREVIOUS_REVISION` and preserve the timestamped `.venv.previous-*` directory until
verification succeeds. Do not delete or replace the database during an ordinary update.

## 11. Roll back code

Use the recorded full `<PREVIOUS_REVISION>`. Rebuild dependencies from that revision instead of
assuming the current venv is compatible.

```bash
(
set -euo pipefail
PREVIOUS_REVISION=<PREVIOUS_REVISION>
ROLLBACK_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FAILED_VENV="/opt/forex-alert-bot/.venv.failed-${ROLLBACK_TIMESTAMP}"
sudo systemctl stop forex-alert-bot.service
sudo git -C /opt/forex-alert-bot checkout --detach "$PREVIOUS_REVISION"
sudo test ! -e /opt/forex-alert-bot/.venv.rollback
sudo test ! -e "$FAILED_VENV"
sudo python3 -m venv /opt/forex-alert-bot/.venv.rollback
sudo /opt/forex-alert-bot/.venv.rollback/bin/python -m pip install --require-hashes \
  -r /opt/forex-alert-bot/requirements-build.lock
sudo /opt/forex-alert-bot/.venv.rollback/bin/python -m pip install --require-hashes \
  --no-build-isolation \
  -r /opt/forex-alert-bot/requirements.lock
sudo /opt/forex-alert-bot/.venv.rollback/bin/python -m pip check
sudo mv /opt/forex-alert-bot/.venv "$FAILED_VENV"
sudo mv /opt/forex-alert-bot/.venv.rollback /opt/forex-alert-bot/.venv
sudo chown -R root:forex-alert-bot /opt/forex-alert-bot
sudo chmod -R u=rwX,g=rX,o= /opt/forex-alert-bot
sudo install -o root -g root -m 0644 \
  /opt/forex-alert-bot/deploy/forex-alert-bot.service \
  /etc/systemd/system/forex-alert-bot.service
sudo systemd-analyze verify /etc/systemd/system/forex-alert-bot.service
sudo systemctl daemon-reload
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --run-once --dry-run
'
sudo -u forex-alert-bot bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --inspect-recent
'
sudo systemctl start forex-alert-bot.service
sudo systemctl status forex-alert-bot.service --no-pager
sudo journalctl -u forex-alert-bot.service --since '-10 minutes' --no-pager
)
```

The block runs and inspects a one-shot dry-run before restarting the scheduler. Inspect the next
scheduled Run after restart. Restore a database backup only when the selected revision is
demonstrably incompatible with current data or the database is corrupt; code rollback alone is not
a reason to discard Run history.

## 12. Gate for issue #32

Keep both controls in place: `DRY_RUN=true` in the external file and `--dry-run` in `ExecStart`.
Issue #32 must review authorized VPS evidence before either control changes:

- a successful one-shot dry-run and at least one completed scheduled Run;
- read-only inspection of Run, Candidate Signal, News Analysis, Alert Decision, Score Adjustment,
  delivery-skip, and Error Record outcomes;
- stable provider behavior with investigated failures;
- journald and systemd restart/stop behavior;
- a validated backup and a controlled restore drill;
- confirmation that logs and operator output do not expose credentials or provider payloads; and
- an explicit, reviewed decision to test and enable Telegram delivery.

Until that review is complete, repository installation can be complete while live VPS acceptance
and issue closure remain pending.
