# Debian 13 on DigitalOcean deployment

This is the authoritative V1 runbook for installing the Forex Alert Bot as one Python service on
Debian 13 on DigitalOcean. It assumes an operator with `sudo` access and an intended application revision
identified by its full Git commit SHA.

The current host is `forex-alert-bot` (`147.182.139.12`, DigitalOcean `nyc1`). See the
[deployment evidence](issue-30-deployment-verification.md) for the verified revision and Run IDs.

> **Current operation:** The owner authorized live Telegram delivery on September 10, 2026.
> The VPS now uses `DRY_RUN=false` and the live override in section 12. The previous #32
> dry-run waiting period is removed. Sections 1–11 retain the initial-install/preflight procedure.
> Do not set `DRY_RUN=false` on a new installation without explicit operator authorization.

The service has no inbound application port. Do not add a firewall rule for it. It makes outbound
DNS and HTTPS requests to the configured providers and Telegram.

## Supported host and layout

Use Debian 13 on DigitalOcean with Python 3.12 or newer. The fixed V1 layout is:

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

Debian 13 supplies Python 3.13. Confirm the displayed Python version is at least 3.12.

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

### Private-repository transfer without VPS GitHub credentials

The deployed host has no GitHub credential. Transfer a reviewed Git bundle over SSH instead of
copying the workstation's private SSH key or GitHub token. On the workstation, with the intended
revision checked out and committed:

```bash
git bundle create /tmp/forex-alert-bot.bundle HEAD
git bundle verify /tmp/forex-alert-bot.bundle
scp -i ~/.ssh/id_ed25519 /tmp/forex-alert-bot.bundle root@147.182.139.12:/root/forex-alert-bot.bundle
```

For the initial install, substitute this clone command in section 3:

```bash
sudo git clone /root/forex-alert-bot.bundle /opt/forex-alert-bot
sudo git -C /opt/forex-alert-bot remote set-url origin https://github.com/kareemnasir/forex-alert-bot.git
```

Skip the network `fetch origin` for that initial install; the bundle contains its own Git history.
For updates, upload a fresh bundle and substitute the following for `fetch --prune origin` in
section 10, then check out the explicit reviewed SHA as usual:

```bash
sudo git -C /opt/forex-alert-bot fetch /root/forex-alert-bot.bundle HEAD
```

Retain the bundle and pin the deployed SHA locally so rollback commits remain reachable:

```bash
sudo git -C /opt/forex-alert-bot tag deploy-<UNIQUE_RELEASE_NAME> <APP_REVISION>
```

The bundle contains committed repository content only; external configuration and SQLite history
stay on the host. Uploading a bundle does not change the running revision.

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
(
set -euo pipefail
sudo test ! -e /etc/forex-alert-bot/forex-alert-bot.env
sudo install -o root -g forex-alert-bot -m 0640 /dev/null \
  /etc/forex-alert-bot/forex-alert-bot.env
sudoedit /etc/forex-alert-bot/forex-alert-bot.env
sudo chown root:forex-alert-bot /etc/forex-alert-bot/forex-alert-bot.env
sudo chmod 0640 /etc/forex-alert-bot/forex-alert-bot.env
sudo ln -s /etc/forex-alert-bot/forex-alert-bot.env /opt/forex-alert-bot/.env
)
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

The file-creation block is for a new installation only and refuses an existing file. If it exists,
preserve it and edit it with `sudoedit`; installing `/dev/null` again would erase existing credentials.
Use plain `KEY=value` assignments without variable interpolation or `export`, so systemd and
python-dotenv read the same values. Keep the verified `OLLAMA_MODEL=gpt-oss:120b-cloud` unless a
real provider check demonstrates that a change is needed.

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

`systemd-analyze verify` must run on the Debian 13 target on DigitalOcean. Static repository tests on another operating
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

Confirm boot enablement with `sudo systemctl is-enabled forex-alert-bot.service`. Capture the
installed definition with `sudo systemctl cat forex-alert-bot.service` (review any local drop-ins
for secrets before sharing). Record `git -C /opt/forex-alert-bot rev-parse HEAD` as root and
`sudo systemctl show forex-alert-bot.service -p ActiveState -p SubState -p NRestarts -p MainPID`.
The unit permits five starts within 300 seconds, waits 30 seconds between failure restarts, and
then leaves rapid persistent failures stopped until the operator fixes the cause and resets it.
On this Debian host the rate-limit drill retained `Result=signal`; verify the journal's
`Start request repeated too quickly` entry and `NRestarts`, rather than requiring the result string
to equal `start-limit-hit`. Inject failures only during a planned maintenance window with no
in-flight Run, then reset the failure state and confirm recovery.

HTTPX request and HTTPCore transport logging are capped at WARNING even with `LOG_LEVEL=DEBUG`;
request URLs and headers can contain credentials. Application scheduling and error diagnostics
remain available. Do not enable those libraries' verbose loggers or share raw provider payloads.

The application handles systemd's `SIGTERM` by waiting for an in-progress signal check to finish,
bounded by the unit's 300-second stop timeout. That budget covers the current default sequential
provider request ceiling (up to 120 seconds of market-data attempts, 10 seconds for news, and 60
seconds of sentiment attempts) with margin for computation and SQLite. Recalculate and, if needed,
raise `TimeoutStopSec` before increasing the pair/timeframe inventory, request timeouts, or retry
counts. Starting an already-active unit does not create a duplicate process. APScheduler also limits
the signal-check job to one concurrent instance.

### V1 weekday policy

All fire times use `APP_TIMEZONE` and remain inside the configured alert window:

- Sunday: the later of 17:00 and the configured start hour through the configured end hour.
- Monday through Thursday: the configured start hour through the configured end hour.
- Friday: the configured start hour through the earlier of 17:00 and the configured end hour.
- Saturday: no Runs.

The default remains `America/Detroit`, 07:00–22:00, at `:00` and `:30` with the final end-hour Run
at `:00`. This approximates the normal Sunday-evening-to-Friday-evening Forex week. It does not
model holidays, exceptional closures, or broker-specific sessions; V1 has no market calendar.
If the configured daily window does not intersect Sunday's or Friday's range, that day has no
Runs. The 17:00 boundary is in `APP_TIMEZONE`; use America/Detroit for the intended US market-week
approximation. One-shot commands run immediately and bypass this schedule. There is no immediate
scheduled Run on startup, and downtime does not create a backlog of historical Runs.

### Verify a scheduled Run

After a configured fire time has passed, do not infer success only from `active (running)`:

1. Check `journalctl -u forex-alert-bot.service` for a signal-check start.
2. Run `--inspect-recent` and identify a new Run created after service start.
3. Run `--inspect-run <RUN_ID>` and require `completed`, `Dry run: yes`, and zero sent Alerts.
4. Review every Error Record and delivery skip.

Require zero persisted provider errors and evidence for all six configured pair/timeframe fetches,
not merely a completed status. Preserve the configured pair/timeframe inventory with the revision
and Run IDs; the current database does not persist successful candle-fetch receipts. The pipeline
attempts each configured combination and records failed fetches. A No Alert outcome with zero
candidates is valid: in that case news and sentiment are not called and no delivery skip is expected.

Repeat these checks after each deployment. See the deployment verification record for observed
VPS results; repository verification alone is not live service evidence.

### Recognize failures

- Configuration error: the process exits before scheduling; `systemctl status` and journald show a
  configuration exception. Correct the external file, then use `systemctl reset-failed` and start.
- Market-data provider: the Run normally completes with a `market-data` Error Record and no usable
  candidate for the affected fetch. Check credentials, provider status, and rate limits.
- News provider: inspect a `news` Error Record and an unavailable News Analysis.
- Sentiment provider: inspect a `sentiment` Error Record and unavailable sentiment; confirm Ollama
  host, model, key, and provider status.
- Telegram: a qualifying final decision must show a `dry_run` delivery skip, not a sent Alert.
  Telegram errors are not expected because delivery is suppressed. Do not use `--telegram-test`
  during issue #30.
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

Run this entire block together: source validation must succeed before stopping anything. Stop
any manually launched scheduler or one-shot too; systemd controls only its own process. A restore
deliberately returns data to the backup time, so retain the current history as shown below.

```bash
(
set -euo pipefail
RESTORE_SOURCE=<ABSOLUTE_BACKUP_PATH>
sudo test -f "$RESTORE_SOURCE"
sudo test -s "$RESTORE_SOURCE"
test "$(sudo sqlite3 -readonly "$RESTORE_SOURCE" 'PRAGMA integrity_check;')" = "ok"
test -z "$(sudo sqlite3 -readonly "$RESTORE_SOURCE" 'PRAGMA foreign_key_check;')"
test "$(sudo sqlite3 -readonly "$RESTORE_SOURCE" \
  "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='runs';")" = "1"
sudo systemctl stop forex-alert-bot.service
test "$(sudo systemctl show forex-alert-bot.service -p ActiveState --value)" = inactive

DATABASE_PATH=/var/lib/forex-alert-bot/forex-alert-bot.sqlite3
RESTORE_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK_DIR="/var/backups/forex-alert-bot/pre-restore-${RESTORE_TIMESTAMP}"
RESTORED_DB="/var/lib/forex-alert-bot/.restore-${RESTORE_TIMESTAMP}.sqlite3"
sudo test ! -e "$ROLLBACK_DIR"
sudo test ! -e "$RESTORED_DB"
sudo install -d -o root -g forex-alert-bot -m 0750 "$ROLLBACK_DIR"
# Preserve existing files even when corrupt; a logical backup may then be impossible.
sudo install -d -o root -g root -m 0700 "$ROLLBACK_DIR/raw"
for suffix in '' -wal -shm; do
  if sudo test -e "${DATABASE_PATH}${suffix}"; then
    sudo cp -p "${DATABASE_PATH}${suffix}" "$ROLLBACK_DIR/raw/forex-alert-bot.sqlite3${suffix}"
  fi
done
sudo sqlite3 "$RESTORED_DB" ".restore '$RESTORE_SOURCE'"
test "$(sudo sqlite3 "$RESTORED_DB" 'PRAGMA integrity_check;')" = "ok"
test -z "$(sudo sqlite3 "$RESTORED_DB" 'PRAGMA foreign_key_check;')"
sudo chown forex-alert-bot:forex-alert-bot "$RESTORED_DB"
sudo chmod 0640 "$RESTORED_DB"
sudo rm -f "${DATABASE_PATH}-wal" "${DATABASE_PATH}-shm"
sudo mv "$RESTORED_DB" "$DATABASE_PATH"
sudo systemctl start forex-alert-bot.service
sudo systemctl status forex-alert-bot.service --no-pager
)
```

Finally inspect journald, run `--inspect-recent`, and open a known Run with `--inspect-run`. If
verification fails, stop the service and recover the raw main/WAL/SHM set kept together in
`ROLLBACK_DIR/raw`; remove the replacement's sidecars first, copy the saved set back, and apply
`forex-alert-bot:forex-alert-bot` ownership and `0640` permissions before restarting. If the saved
database was already corrupt, retain it for diagnosis and select another validated backup.

### Non-destructive restore drill

For deployment acceptance, restore a validated backup to an isolated directory without replacing
production history. Use the backup path from section 8. This verifies SQLite recovery and CLI
readability; it does not prove service ownership or systemd behavior until executed on the VPS.

```bash
(
set -euo pipefail
RESTORE_SOURCE=<ABSOLUTE_BACKUP_PATH>
sudo test -s "$RESTORE_SOURCE"
DRILL_DIR="$(sudo mktemp -d /var/lib/forex-alert-bot/restore-drill-XXXXXXXX)"
sudo chown forex-alert-bot:forex-alert-bot "$DRILL_DIR"
sudo chmod 0750 "$DRILL_DIR"
DRILL_DB="$DRILL_DIR/restored.sqlite3"
sudo sqlite3 "$DRILL_DB" ".restore '$RESTORE_SOURCE'"
sudo chown forex-alert-bot:forex-alert-bot "$DRILL_DB"
sudo chmod 0640 "$DRILL_DB"
test "$(sudo -u forex-alert-bot sqlite3 -readonly "$DRILL_DB" 'PRAGMA integrity_check;')" = ok
test -z "$(sudo -u forex-alert-bot sqlite3 -readonly "$DRILL_DB" 'PRAGMA foreign_key_check;')"
test "$(sudo sqlite3 -readonly "$RESTORE_SOURCE" '.dump' | sha256sum)" = \
  "$(sudo -u forex-alert-bot sqlite3 -readonly "$DRILL_DB" '.dump' | sha256sum)"
sudo -u forex-alert-bot env DATABASE_PATH="$DRILL_DB" bash -c '
  cd /opt/forex-alert-bot
  exec .venv/bin/python -m forex_alert_bot --inspect-recent
'
printf 'Retained restore drill: %s\n' "$DRILL_DIR"
)
```

Record the backup path, restored Run IDs, comparison result, and integrity checks. Retain the drill
until acceptance is recorded. Use the same `DATABASE_PATH` override with `--inspect-run <RUN_ID>`
to compare a known Run against the backup. Never point a scheduler or provider run at the drill.
The `.restore` runs as root because a WAL-mode backup can require sidecar creation in the
root-owned backup directory even when reading. The restored copy is owned and inspected by the
service user in its writable drill directory.

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

## 12. Gate for issue #32 — replaced by authorized live operation

On September 10, 2026 the owner removed the three-trading-day / 50-run dry-run prerequisite and
explicitly authorized live Telegram delivery. [Issue #32](https://github.com/kareemnasir/forex-alert-bot/issues/32)
now tracks ongoing live operation and alert quality; it does not block startup or require dry-run.

### Current live service

The external environment file contains `DRY_RUN=false`. The base unit remains the initial-install
unit; the persistent `/etc/systemd/system/forex-alert-bot.service.d/20-live.conf` override resets its
command to remove the one-way CLI dry-run override:

```ini
[Unit]
Description=Forex Alert Bot scheduled live service

[Service]
ExecStart=
ExecStart=/opt/forex-alert-bot/.venv/bin/python -m forex_alert_bot --schedule
```

This definition is versioned as [deploy/forex-alert-bot-live.conf](../deploy/forex-alert-bot-live.conf).
The override survives base-unit installation during an update or rollback. Do not delete it during
routine deployment. The current live host does not need to repeat activation or the test message.

To reproduce an explicitly authorized live activation: stop the service, validate a section 8
backup, record the UTC boundary and maximum Run ID, then change only `DRY_RUN` to `false` using
`sudoedit /etc/forex-alert-bot/forex-alert-bot.env`. Preserve root:forex-alert-bot ownership and 0640
permissions. Install the reviewed override:

```bash
sudo install -d -o root -g root -m 0755 /etc/systemd/system/forex-alert-bot.service.d
sudo install -o root -g root -m 0644 \
  /opt/forex-alert-bot/deploy/forex-alert-bot-live.conf \
  /etc/systemd/system/forex-alert-bot.service.d/20-live.conf
sudo systemd-analyze verify /etc/systemd/system/forex-alert-bot.service
sudo systemctl daemon-reload
sudo systemctl start forex-alert-bot.service
sudo systemctl is-enabled forex-alert-bot.service
sudo systemctl show forex-alert-bot.service -p ActiveState -p SubState -p NRestarts -p ExecStart
```

The running Python command must contain `--schedule` without `--dry-run`, and the actual process
must have `DRY_RUN=false`. Inspect these values without dumping the rest of the process environment.
A live one-shot uses `--run-once` without `--dry-run` and may send a real alert; execute it only when
intended. The optional `--telegram-test` command sends a real test message and was already verified
once at activation. A connectivity test is separate from a strategy-generated alert.

### Begin the #32 observation period

The previous dry-run observation procedure is superseded. Live monitoring began at
2026-09-10T18:39:26.314622+00:00, with archived baseline Run ID 3 and manual live Run 4. Keep the
archive and original runtime history. Do not run automated tests against the production database.

Inspect the next natural scheduled Run through journald and `--inspect-run`; require live mode and
review all persisted errors and decisions. Continue tracking the six configured pair/timeframe
combinations, natural candidates, news/sentiment, adjustments, cooldown/delivery skips and sent
alerts. No Alert is valid; enabling delivery does not force a signal or send a periodic heartbeat.

The first naturally qualifying candidate-to-Telegram path remains unverified until it occurs.
Neither the successful connectivity message nor separate provider checks establish that path.
There is no three-day or 50-run gate. Record real evidence before proposing any strategy tuning.

If delivery or behavior is wrong, use `sudo systemctl stop forex-alert-bot.service`, inspect the
persisted records and journal, and follow the code rollback instructions while retaining SQLite.
Use `sudo systemctl start forex-alert-bot.service` after resolving the cause.

See [the deployment verification record](issue-30-deployment-verification.md) for the initial
acceptance evidence and subsequent live cutover.
