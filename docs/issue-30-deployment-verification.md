# Issue #30 deployment verification

Date: September 10, 2026. Status: **implementation prepared; VPS acceptance blocked**.
Source of truth: [issue #30](https://github.com/kareemnasir/forex-alert-bot/issues/30).

## Revision and host

The deployment implementation already merged in
[PR #52](https://github.com/kareemnasir/forex-alert-bot/pull/52), main revision
`3c7f41e247d33af562f78a141e8f19cb9b3b9ed4`. Dependencies #47, #31 and #50 are closed.
This follow-up fixes HTTP request logging and recovery instructions and adds the #32 start procedure.

No target VPS hostname/IP, SSH username, port or usable key/access method was supplied or found
in the available SSH configuration. Sudo capability is unknown. Access details have been requested;
do not put passwords or private keys in the issue or PR. No server was modified.

- Deployment/service status: unknown; no VPS connection made.
- Deployed revision: unverified (the main SHA above is a repository revision).
- VPS one-shot Run ID: none verified.
- VPS scheduled Run ID: none verified.
- Installed unit: unverified; intended definition is [deploy/forex-alert-bot.service](../deploy/forex-alert-bot.service).
- No real-provider run or Telegram send was executed during this follow-up.

## Acceptance evidence

| Criterion | Repository preparation | VPS evidence |
| --- | --- | --- |
| Debian 13 / Python / dependencies | Runbook with system Python 3.13, venv, hash-locked build/runtime installs | Pending |
| Dedicated unprivileged user | nologin `forex-alert-bot` user/group and unit identity | Pending |
| WorkingDirectory / ExecStart / EnvironmentFile | Checked-in unit; `--schedule --dry-run` remains explicit | Pending |
| External protected secrets | `/etc/forex-alert-bot/forex-alert-bot.env`, root:service group, 0640; creation refuses existing file | Pending |
| Persistent SQLite directory and ownership | `/var/lib/forex-alert-bot`, service ownership, 0750 | Pending |
| DRY_RUN=true | Required external value plus one-way CLI override | Pending |
| Bounded restart / boot startup | on-failure, 30s delay, five starts/300s; enable/is-enabled commands | Pending |
| Operations and inspection | start/stop/restart/status/update, journald and read-only CLI commands | Pending |
| SQLite backup / restore | WAL-safe backup and isolated drill; local recovery checks below | VPS drill pending |
| API config / successful one-shot / scheduled Run | Explicit zero-provider-error and persisted-decision checks | Pending |
| Rollback preserves history | Full previous SHA, rebuilt locked environment, external database preserved | VPS rollback pending |
| Forex weekday/session policy | Sunday 17:00 through Friday 17:00 intersected with daily window in America/Detroit; Saturday excluded | Code/tests verified; host schedule pending |

All pending rows must be verified on the identified Debian 13 DigitalOcean host before closing #30.
Repository tests and PR completion do not complete those rows.

## Local checks

- `python -m pytest -q`: **337 passed** using the existing local virtual environment.
- `ruff check .`: passed; `ruff format --check .`: passed.
- Regression proof: a real HTTPX client with MockTransport and an explicitly fake token emitted the
  token before the fix; both INFO and DEBUG cases failed. Both pass after suppressing HTTPX INFO
  and HTTPCore DEBUG transport records. No real credentials or network calls were used.
- SQLite CLI and Bash recovery drill used disposable databases only. A backup included committed
  WAL content while its source connection remained open. The documented restore block recovered
  existing, missing and corrupt target databases, preserving pre-existing bytes where present.
  An invalid source stopped before any service or database operation. Integrity and foreign-key
  checks passed. Identity/ownership and systemctl calls were simulated; this proves local SQLite
  and shell behavior, not Debian permissions or a running systemd service.
- Review reproduced a WAL backup failing to restore from a non-writable backup directory despite
  readable file permissions. The drill now restores as root and assigns the restored copy to the
  service user before inspection. Local review passes ran sequentially in the main agent context;
  an independent cross-model pass was rejected by automatic approval review before it started.
- The complete test suite's runtime guard verified that the original local database and its WAL/SHM
  files were unchanged. The pre-existing documentation commit remains on
  `codex/digitalocean-debian-docs`; it is excluded from this follow-up PR.

## Existing provider evidence and remaining gap

The supplied local Run 79 evidence remains scoped to revision `f25d05f`: all six Twelve Data
pair/timeframe combinations succeeded, zero provider errors, zero candidates, and No Alert technical
and final decisions. Separate Marketaux, Ollama `gpt-oss:120b-cloud` validation with real articles,
and Telegram read-only access checks were successful. No Telegram message was sent.

These are prior local checks, not VPS Runs. The naturally qualifying candidate → news → adjusted
decision → dry-run delivery-skip path remains unverified. Do not force candidates or change strategy
thresholds to produce that evidence. A provider-successful No Alert is sufficient for #30's run check.

## Resume deployment and begin #32

Supply the VPS IP/hostname, SSH user/port and key path or configured access method, plus sudo access.
Inspect the server before applying the [deployment runbook](vps-deployment.md), preserving any
existing deployment, secrets and runtime history. Record the installed full SHA and both VPS Run IDs
here, then replace each pending acceptance row with observed evidence.

Begin #32 using [the exact observation procedure](vps-deployment.md#begin-the-32-observation-period):
stop and archive the deployment database, record UTC start boundary and baseline maximum Run ID,
restart with both dry-run controls intact, and collect at least three trading days and 50
provider-successful scheduled Runs. Keep the archive and runtime history, exclude manual Runs,
inspect all persisted outcomes, and report any remaining natural-candidate coverage gap.
