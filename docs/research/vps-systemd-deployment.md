# VPS and systemd deployment research

Verified against primary sources on 2026-08-20. This note records the deployment decisions that
affect issue #30; it is not the operator runbook.

## Supported platform and Python baseline

Use Debian 13 on DigitalOcean for V1. Debian 13 (trixie) supplies Python 3.13,
which meets the application's Python 3.12-or-newer requirement. The Ruff target remains the
minimum supported Python version, not the deployment interpreter version.
([Debian 13 release information](https://www.debian.org/releases/trixie/),
[Debian python3-venv package](https://packages.debian.org/trixie/python3-venv))

The minimal host packages are `python3`, `python3-venv`, `sqlite3`, and `git`.
Install them using the runbook's apt commands. The existing dependency locks were generated
for the Python 3.12 baseline; installation and service validation on the Debian 13 host remain
required deployment evidence.

## systemd unit decisions

Use one system service with an unprivileged static user and group, `Type=simple`, an explicit
`WorkingDirectory=/opt/forex-alert-bot`, and the absolute virtual-environment interpreter in
`ExecStart`, for example `/opt/forex-alert-bot/.venv/bin/python -m forex_alert_bot --schedule`.
An absolute interpreter path does not depend on shell activation, and the foreground
`BlockingScheduler.start()` is a natural main process for a simple service. APScheduler documents
that `BlockingScheduler` runs in the foreground and that `start()` blocks. ([Python `venv`
documentation](https://docs.python.org/3.12/library/venv.html), [APScheduler 3 blocking scheduler
API](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/blocking.html))

Use both `Wants=network-online.target` and `After=network-online.target`. The former pulls the
active target into the boot transaction and the latter orders this network-client service after it;
what "online" means is still defined by the host's network manager and is not a continuing
reachability guarantee. Provider failures therefore still need the application's existing failure
isolation. ([systemd network-online guidance](https://systemd.io/NETWORK_ONLINE/))

Use a required external `EnvironmentFile=/etc/forex-alert-bot/forex-alert-bot.env`; do not prefix
the path with `-`, because a missing production configuration should fail startup. Environment
files contain newline-separated assignments and are read by the service manager shortly before
execution. They keep values out of the repository, unit, and command line, but systemd explicitly
warns that environment variables are not an ideal secret transport. Given the application's current
environment-variable contract, mitigate that limitation with `root:forex-alert-bot` ownership and
mode `0640`, and never pass secret values as CLI arguments. A future move to systemd credentials
would require application support and is outside this issue. ([systemd `EnvironmentFile=` and
environment security](https://www.freedesktop.org/software/systemd/man/255/systemd.exec.html#Environment))

Use `Restart=on-failure` plus a delay such as `RestartSec=30s`. systemd recommends
`on-failure` for long-running services; deliberate `systemctl stop` operations do not cause a
restart. Bound persistent failure loops with explicit unit start limits, for example
`StartLimitIntervalSec=300` and `StartLimitBurst=5`. Once the burst is exhausted inside the
interval, systemd refuses another start until the interval passes or an operator resets the failed
state. ([systemd `Restart=`](https://www.freedesktop.org/software/systemd/man/255/systemd.service.html#Restart=),
[systemd start-rate limiting](https://www.freedesktop.org/software/systemd/man/255/systemd.unit.html#StartLimitIntervalSec=interval))

The following filesystem and privilege restrictions fit the current application:

- `NoNewPrivileges=true` prevents the service and its descendants from gaining privileges through
  `execve()`.
- `ProtectSystem=strict` makes the filesystem hierarchy read-only to the service, while
  `ReadWritePaths=/var/lib/forex-alert-bot` carves out the one persistent write location needed for
  the SQLite database, WAL, and shared-memory files. `ReadWritePaths=` does not grant ordinary Unix
  permissions, so the directory must also be owned by the service user.
- `ProtectHome=true` is compatible because source, configuration, state, and backup paths are all
  outside `/home`, `/root`, and `/run/user`.
- `PrivateTmp=true` gives the process private writable temporary directories and remains compatible
  with `ProtectSystem=strict`.
- `UMask=0027` prevents newly created state from being world-readable or writable. Existing files
  still need explicit ownership and modes.

These behaviors are defined together in the systemd execution-environment manual. They preserve
read access to `/opt/forex-alert-bot` and `/etc/forex-alert-bot`, outbound DNS/HTTPS, Python imports,
and journald sockets while limiting writes to `/var/lib/forex-alert-bot`. Do not grant the running
service write access to `/opt`, `/etc`, or `/var/backups`; code updates, configuration changes, and
manual backups are operator actions. ([systemd sandboxing, path, and umask directives](https://www.freedesktop.org/software/systemd/man/255/systemd.exec.html))

Set `StandardOutput=journal` and `StandardError=journal` explicitly even though journald is the
normal system-service default. Operators can filter by unit with
`journalctl -u forex-alert-bot.service` and follow new entries with `-f`. Access to the system
journal is itself permission-controlled. ([systemd output handling](https://www.freedesktop.org/software/systemd/man/255/systemd.exec.html#StandardOutput=),
[`journalctl`](https://www.freedesktop.org/software/systemd/man/255/journalctl.html))

One active service unit already gives systemd a single supervised main process: starting an already
active unit does not launch a second copy, and restart is implemented as stop followed by start.
The repository additionally configures the scheduled job with `max_instances=1`, which prevents a
second occurrence of that job from overlapping a still-running occurrence inside the process.
([systemd service restart semantics](https://www.freedesktop.org/software/systemd/man/255/systemd.service.html),
[APScheduler maximum instances](https://apscheduler.readthedocs.io/en/3.x/userguide.html#limiting-the-number-of-concurrently-executing-instances-of-a-job))

## Graceful shutdown

systemd's normal first stop signal is `SIGTERM`; if processes remain after `TimeoutStopSec=`, it
escalates to `SIGKILL` by default. Python installs a default `KeyboardInterrupt` translation for
`SIGINT`, not `SIGTERM`, and Python-level signal handlers run in the main Python thread. Therefore,
graceful systemd shutdown requires an explicit main-thread `SIGTERM` handler rather than relying on
the behavior seen with Ctrl-C. ([systemd kill behavior](https://www.freedesktop.org/software/systemd/man/255/systemd.kill.html),
[Python 3.12 signal rules](https://docs.python.org/3.12/library/signal.html))

The handler should request `BlockingScheduler.shutdown(wait=True)`. APScheduler documents that this
does not interrupt a running job and waits for executing jobs to finish. Configure a finite
`TimeoutStopSec` long enough for the application's bounded provider calls and one in-progress Run;
systemd's later `SIGKILL` remains the final bound if shutdown hangs. ([APScheduler 3 blocking
scheduler API](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/blocking.html#apscheduler.schedulers.blocking.BlockingScheduler.shutdown),
[systemd service timeouts](https://www.freedesktop.org/software/systemd/man/255/systemd.service.html#TimeoutStopSec=))

The selected V1 unit uses `TimeoutStopSec=300s`. With the shipped defaults, sequential request
ceilings are at most 120 seconds for six market-data fetches with one retry, 10 seconds for news,
and 60 seconds for sentiment with one retry, leaving margin for local computation and SQLite. This
is a configuration contract: operators must revisit the stop budget before increasing request
timeouts, retry counts, pairs, or timeframes.

## Virtual-environment and dependency expectations

Create the venv in the fixed application tree with
`python3 -m venv /opt/forex-alert-bot/.venv`. A venv is isolated from system packages by default, bootstraps `pip`
unless `--without-pip` is used, does not need activation when its interpreter is invoked directly,
and should be recreated rather than moved or copied. ([Python 3.12 `venv`
documentation](https://docs.python.org/3.12/library/venv.html))

Keep `requirements.txt` as the human-maintained direct-dependency input, but install the generated
`requirements.lock` into the service venv with pip's `--require-hashes` mode. Because `ta` is
source-only, first install the separately hash-locked `requirements-build.lock`, then install the
runtime lock with `--no-build-isolation`; this prevents pip from resolving an unreviewed isolated
build environment. The locks pin both transitive graphs for Python 3.12 and record accepted
distribution hashes, so the reviewed revision also identifies its install inputs. Do not perform an
unpinned pip self-upgrade on the VPS.
`requirements-dev.txt` is for repository verification tools, not service startup; install it only in
a disposable verification environment or deliberately on the VPS when tests and Ruff are to run
there. During update or rollback, recreate the venv from the selected revision's lock instead of
assuming the previous dependency set remains compatible. ([pip secure installs and hash-checking
mode](https://pip.pypa.io/en/stable/topics/secure-installs/))

## WAL-safe SQLite backup and restore

This repository enables WAL mode. In WAL mode the `-wal` file is part of the database's persistent
state; separating it from the main file can lose committed transactions or corrupt the copied
database. Therefore never make an online backup by copying only
`/var/lib/forex-alert-bot/forex-alert-bot.sqlite3`. ([SQLite WAL file
rules](https://www.sqlite.org/wal.html#the_wal_file))

For a manual online backup, run the SQLite CLI as the service user and use its `.backup` command to
write a new timestamped file under `/var/backups/forex-alert-bot`. `.backup` uses SQLite's supported
backup mechanism; the Online Backup API produces a consistent snapshot while allowing the source to
remain in use, holding source locks only while pages are read. Use a freshly named destination and
fail if it already exists rather than overwriting a known-good backup. ([SQLite CLI `.backup`](https://www.sqlite.org/cli.html#special_commands),
[SQLite Online Backup API](https://www.sqlite.org/backup.html))

Immediately validate the completed backup with:

```sql
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

`integrity_check` must return exactly `ok`; `foreign_key_check` must return no rows, because
`integrity_check` does not detect foreign-key violations. Apply restrictive ownership and mode to
the finished backup only after both checks succeed. ([SQLite integrity and foreign-key check
pragmas](https://www.sqlite.org/pragma.html#pragma_integrity_check))

Restoration is an offline operation:

1. Validate the selected backup before touching active state, then stop the service and confirm it
   is inactive.
2. While stopped, create a timestamped pre-restore rollback snapshot with `.backup`. This preserves
   the complete logical database even if WAL sidecars still exist.
3. Restore the selected backup into a new temporary database with the CLI's `.restore` command and
   run both integrity checks against that temporary database.
4. Preserve the old main database and any `-wal`/`-shm` sidecars together in a timestamped rollback
   location; do not leave old sidecars beside the replacement main file. Atomically place the
   validated restored file at the configured database path, then reapply service ownership and
   restrictive permissions.
5. Start the service, inspect status and journald, and use the repository's read-only inspection CLI
   to confirm that Run history is readable.

The SQLite CLI officially provides both `.backup` and `.restore`; using them avoids treating a live
WAL database as a single ordinary file. A database restore is warranted for database loss or
corruption, not for an ordinary code rollback: updates and code rollbacks should preserve the
persistent database by default. ([SQLite CLI backup and restore commands](https://www.sqlite.org/cli.html#special_commands),
[SQLite database and WAL state](https://www.sqlite.org/fileformat.html#hot_journals))

## Resulting V1 choices

- Keep the exact layout proposed by the issue: source and venv in `/opt/forex-alert-bot`, external
  environment in `/etc/forex-alert-bot/forex-alert-bot.env`, SQLite state in
  `/var/lib/forex-alert-bot`, and operator-managed backups in `/var/backups/forex-alert-bot`.
- Start only `python -m forex_alert_bot --schedule --dry-run` as the dedicated user, with
  `DRY_RUN=true` in the external environment file. Live Telegram delivery remains gated on issue
  #32.
- Use a small, verified hardening set rather than syscall or network filters that could accidentally
  block DNS, HTTPS, Python extensions, or SQLite.
- Validate the unit on the Debian 13 target on DigitalOcean with `systemd-analyze verify`; local static checks are not
  evidence that systemd executed it on a VPS.
