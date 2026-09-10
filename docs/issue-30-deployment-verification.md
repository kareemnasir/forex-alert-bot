# Deployment verification: September 10, 2026

Date: September 10, 2026. Status: **deployment verified; live delivery enabled**.
Source of truth: [issue #30](https://github.com/kareemnasir/forex-alert-bot/issues/30).
Changes and evidence: [PR #53](https://github.com/kareemnasir/forex-alert-bot/pull/53).
PR #53 was merged as `dcf2bf6830c1dedb18f82bfba38a6fde54ae7cf4`; issue #30 is closed.
Issue #32 was subsequently closed as not planned, with remaining monitoring checks unverified.

## Live cutover — September 10, 2026, 18:39 UTC

Live Telegram delivery was enabled after the initial deployment checks. The earlier three-day / 50-run observation plan was not completed.
The following initial-deployment evidence is historical; its dry-run controls and no-message claims
apply before this cutover. The [monitoring issue](https://github.com/kareemnasir/forex-alert-bot/issues/32) preserves the live activation record and remaining checks; its closure does not establish that those checks passed.

- Application revision remains `4d81a389500122269b23b2d023e1b09cdfcdcd18`.
- The external file now has `DRY_RUN=false`, verified in the actual scheduler environment.
- Persistent override `/etc/systemd/system/forex-alert-bot.service.d/20-live.conf` sets the effective
  command to `/opt/forex-alert-bot/.venv/bin/python -m forex_alert_bot --schedule` without `--dry-run`.
  See [the live override](../deploy/forex-alert-bot-live.conf). Native systemd validation passed.
- Exactly one test message, “Forex alert bot Telegram test message.”, was
  accepted by Telegram at 18:39:25 UTC. It is a connectivity test, not a generated Alert record.
- Live manual **Run 4**, 18:39:26.886844–18:39:29.959864 UTC: completed, `dry_run=0`, zero errors,
  zero candidates, technical decision #7 and final decision #8 both No Alert/score 0, zero generated
  alerts. No candidate was forced; the full natural candidate-to-delivery path remains unverified.
- Enabled service started at 18:39:30 UTC, PID 1383, active/running, `NRestarts=0`. Its command and
  environment independently confirmed live mode. The inspected journal had no configured secrets.
- Pre-live backup `/var/backups/forex-alert-bot/pre-live-20260910T183924Z.sqlite3` passed integrity
  and foreign-key checks. Baseline maximum Run ID 3; original database/history retained.
- Safe activation/verification reports remain under `/root/issue30-evidence/` as
  `live-cutover.json` and `live-verification.json`. Run 4 is manual. Natural live scheduled Run 5 completed at 19:00 UTC with zero errors, zero candidates, and No Alert decisions; its database record was checked over SSH.
- Follow-up inspection confirmed natural live Run 6 at 19:30 UTC / 3:30 PM Detroit also completed with zero errors, zero candidates, and zero sent alerts.

## Host and deployed revision

- DigitalOcean Droplet `forex-alert-bot` in `nyc1`. Host access details are maintained outside this guide.
- Debian GNU/Linux 13 (trixie), Debian version 13.5; Python 3.13.5; systemd 257.13.
- SSH port 22, root UID 0; administrative access verified after the operator unlocked the local key.
- Pinned ED25519 host fingerprint: `SHA256:MKsvP2lDgmH1STyESUqAPYagJ3X1nyKz6ZbK8uSwN/g`.
  This was first-use trust, followed by strict host-key checking. Authenticated hostname and
  DigitalOcean link-local metadata matched the supplied host; no independent console fingerprint
  attestation was obtained.
- Deployed application revision: `4d81a389500122269b23b2d023e1b09cdfcdcd18`.
  Later documentation-only commits in PR #53 are not claimed as the running application revision.
- The initial host had no existing bot installation, service user, or database. Existing local runtime history and unrelated Git work were preserved.

A Git bundle transferred the committed repository over SSH; no workstation private key or GitHub
credential was installed on the VPS. The checkout is detached, root-owned and service-readable at
`/opt/forex-alert-bot`. The runbook now documents bundle-based updates for this private repository.

## Initial dry-run acceptance evidence

| Criterion | Observed VPS result |
| --- | --- |
| Debian/Python/dependencies | Debian 13; Python 3.13.5 venv; hash-checked build/runtime locks, no build isolation; `pip check` clean. |
| Dedicated unprivileged user | `forex-alert-bot`, UID 103/GID 104, nologin; running process uses that identity. |
| Unit paths | Installed definition below exactly matches the checked-in unit; native `systemd-analyze verify` passed. |
| Protected external secrets | `/etc/forex-alert-bot/forex-alert-bot.env`, root:forex-alert-bot 0640; parent 0750. Repository `.env` is a symlink to this external file. |
| Persistent runtime ownership | `/var/lib/forex-alert-bot`, service owner/group 0750; SQLite database service owner/group 0640. |
| Dry-run controls | External `DRY_RUN=true`, verified in the actual process environment; literal `--schedule --dry-run` in the running command. |
| Bounded failure restart | 30-second retries observed; five-start/300-second limit stopped the service; operator reset recovered it. See drill below. |
| Boot startup | Enabled; real reboot changed boot ID and automatically started the service at 18:08:46 UTC, active/running with zero restarts. |
| Operations/inspection | Start, stop, restart, status, locked update and rollback exercised; journald and operator CLI inspected. Commands are in the runbook. |
| SQLite backup/restore | Online backup, isolated restore, logical-content comparison, service-user inspection and integrity/FK checks passed. |
| API configuration/one-shot | All credentials present without displaying values; Run 1 completed dry-run with zero persisted errors and No Alert decisions. Six independent candle fetches and news/LLM/read-only Telegram checks passed. |
| Scheduled Run | Run 3 started naturally at 18:30 UTC, completed with zero errors, No Alert technical/final decisions and zero sent alerts; journal trigger correlated with SQLite timestamps. |
| Rollback/history | Previous revision rebuilt and exercised as Run 2; Run 1 unchanged, database retained, intended revision rebuilt and restored. |
| Forex sessions | America/Detroit, :00/:30, 07:00–22:00 intersected with Sunday 17:00–Friday 17:00; Saturday excluded. Natural trigger verified at 14:30 EDT / 18:30 UTC; next trigger 15:00 EDT / 19:00 UTC. |

The session policy approximates the normal Forex week; it has no holiday or broker-specific
calendar. One-shots bypass the schedule. Startup does not immediately execute a scheduled Run.

## Initial base unit definition

`/etc/systemd/system/forex-alert-bot.service`, root:root 0644, byte-for-byte compared with
[the deployed unit](https://github.com/kareemnasir/forex-alert-bot/blob/4d81a389500122269b23b2d023e1b09cdfcdcd18/deploy/forex-alert-bot.service):

```ini
[Unit]
Description=Forex Alert Bot scheduled dry-run service
Documentation=https://github.com/kareemnasir/forex-alert-bot/blob/main/docs/vps-deployment.md
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=forex-alert-bot
Group=forex-alert-bot
WorkingDirectory=/opt/forex-alert-bot
EnvironmentFile=/etc/forex-alert-bot/forex-alert-bot.env
ExecStart=/opt/forex-alert-bot/.venv/bin/python -m forex_alert_bot --schedule --dry-run

Restart=on-failure
RestartSec=30s
KillSignal=SIGTERM
TimeoutStopSec=300s

StandardOutput=journal
StandardError=journal
SyslogIdentifier=forex-alert-bot

UMask=0027
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
CapabilityBoundingSet=
AmbientCapabilities=
ReadWritePaths=/var/lib/forex-alert-bot

[Install]
WantedBy=multi-user.target
```

Process inspection also confirmed no effective capabilities, `NoNewPrivs=1`, the expected working
command, and agreement between every external configuration assignment and the actual process
environment. No secret values were printed.

## Initial dry-run evidence

Database: `/var/lib/forex-alert-bot/forex-alert-bot.sqlite3`.
Inventory: EUR/USD, GBP/USD, USD/JPY × 15min and 1h; all three V1 technical strategies enabled.
Market data: Twelve Data; news: Marketaux; Ollama Cloud model: `gpt-oss:120b-cloud`.

| Run | Origin/revision | UTC start → finish | Persisted result |
| --- | --- | --- | --- |
| 1 | Manual deployment one-shot, `4d81a38` | 18:00:44.805448 → 18:00:52.834021 | completed, dry_run=1, 0 errors, 0 candidates, 0 sent alerts |
| 2 | Manual rollback drill, `3c7f41e` | 18:07:02.401413 → 18:07:20.784187 | completed, dry_run=1, 0 errors, 0 candidates, 0 sent alerts |
| 3 | Natural scheduled Run, `4d81a38` | 18:30:00.013431 → 18:30:22.961267 | completed, dry_run=1, 0 errors, 0 candidates, 0 sent alerts |

Run 1 has technical decision #1 and final decision #2: both No setup / No Alert, score 0.
News Analysis #1 is `no_relevant_news`; no candidate caused a news or sentiment call. Score
Adjustment #1 links decisions #1 → #2 with delta 0. Cooldown skips and delivery skips are both 0;
no qualifying decision reached delivery. Run 2 also has one technical and one final No Alert
decision. Runs 1 and 2 were manual checks, not evidence of unattended scheduling.

Run 3 has News Analysis #3 (`no_relevant_news`), technical decision #5 and final decision #6
(both No setup / No Alert, score 0), and Score Adjustment #3 with delta 0. There are no cooldown
skips or delivery skips. The journal records the scheduled 14:30 EDT trigger at 18:30:00 UTC and
successful job completion at 18:30:22 UTC; no manual one-shot ran in that interval. The initial
inspection caught the Run still in progress; only the later completed record earned acceptance.
At 18:30:51 UTC the service remained enabled, active/running, PID 903, with `NRestarts=0`.
All three retained Runs have zero sent alerts; SQLite integrity and foreign-key checks passed.

The pipeline attempts every configured pair/timeframe and records failed fetches. Zero persisted
errors plus the unchanged six-combination inventory support provider success; SQLite does not
store per-fetch success receipts. Separate real-provider diagnostics on the VPS returned 200
normalized candles for each of the six combinations, with latest candle time 18:00 UTC.

Separate component diagnostics returned three relevant Marketaux articles with zero errors;
Ollama sentiment validation succeeded on attempt 1 using those real articles, covering all three
pairs. Telegram `getMe` and `getChat` returned HTTP 200 / `ok=true`. Those diagnostics neither
created candidates nor wrote pipeline records. **No Telegram messages were sent.**

The real, naturally qualifying candidate → news → adjusted decision → dry-run delivery-skip path
remains unverified. Independent component checks do not establish that integration path. No
candidate was forced and no threshold was changed. A provider-successful No Alert is valid for
#30; the remaining integration gap is recorded below.

## Recovery and service drills

- Online backup: `/var/backups/forex-alert-bot/forex-alert-bot-20260910T180206Z.sqlite3`,
  root:forex-alert-bot 0640, containing Run 1. Integrity check: `ok`; foreign-key check: no rows.
- Isolated restored database:
  `/var/lib/forex-alert-bot/restore-drill-Fcwcig7f/restored.sqlite3`.
  Directory 0750 and database 0640, both service-owned. Logical `.dump` SHA-256 matched the backup;
  service-user `--inspect-run 1` reproduced the record. The production database was not replaced.
- Graceful stop at 18:03:06 UTC logged clean scheduler shutdown, `Result=success`, exit status 0.
- While idle, deliberate process termination exercised retries at 18:03:37, 18:04:08, 18:04:38 and
  18:05:09 UTC. At 18:05:40 the fifth retry was refused with `Start request repeated too quickly`,
  `NRestarts=5`, and failed state. Debian retained `Result=signal`; the drill helper's assertion
  expecting `start-limit-hit` failed, but journal and state verified the intended bound. This
  observation is now in the runbook. `reset-failed` followed by start restored service.
- Rollback stopped the service, checked out previous main revision
  `3c7f41e247d33af562f78a141e8f19cb9b3b9ed4`, rebuilt locked dependencies, and verified Run 1's
  logical database content was unchanged before executing manual Run 2. The previous revision's
  one-shot used `LOG_LEVEL=WARNING` because it predates the transport-log fix. The intended
  `4d81a38` revision was then restored with another fresh locked environment and validated unit.
  Both prior environments remain in `.venv.issue30-preserved` and
  `.venv.issue30-rollback-preserved` under `/opt/forex-alert-bot`; all runtime history remains.
- A real reboot changed boot ID from `26185d85-8371-4fd1-b53e-b48a75b4cd79` to
  `02ee1c1b-8165-4b05-98de-baf43c6a5eda`. The enabled unit started automatically at 18:08:46 UTC;
  scheduler startup was logged at 18:08:48 UTC. Post-reboot PID 648 ran with zero restarts.
  An explicit `systemctl restart` at 18:15:19 UTC succeeded; PID 903 subsequently executed Run 3.

Host evidence files are retained under `/root/issue30-evidence/`, including one-shot output,
recovery paths, pre-reboot boot ID, `scheduled-run.json`, `scheduled-run.txt`, and journal captures. The inspected journal contained none of
the configured secret values. Do not publish unreviewed logs or configuration contents.

## Verification commands and checks

Commands were run over strict host-key-checked SSH. Operator commands ran as the service user
from `/opt/forex-alert-bot`, with the external configuration linked at `.env`:

```bash
cd /opt/forex-alert-bot
sudo -u forex-alert-bot .venv/bin/python -m forex_alert_bot --run-once --dry-run
sudo -u forex-alert-bot .venv/bin/python -m forex_alert_bot --inspect-recent
sudo -u forex-alert-bot .venv/bin/python -m forex_alert_bot --inspect-run 1
sudo -u forex-alert-bot .venv/bin/python -m forex_alert_bot --inspect-run 3
sudo systemd-analyze verify /etc/systemd/system/forex-alert-bot.service
sudo systemctl is-enabled forex-alert-bot.service
sudo systemctl show forex-alert-bot.service -p ActiveState -p SubState -p NRestarts -p MainPID
sudo journalctl -u forex-alert-bot.service --no-pager
sudo sqlite3 -readonly /var/lib/forex-alert-bot/forex-alert-bot.sqlite3 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Results: one-shot exit 0, explicit persisted decisions/errors inspected, unit validation passed,
enabled and active/running after reboot, SQLite integrity `ok` and no foreign-key violations.
The one-shot command records what was executed. Keep manual checks distinct from naturally scheduled runs when evaluating unattended operation.

- Local complete suite: **337 passed**; Ruff lint and formatting passed. The runtime guard confirmed
  the original local database and sidecars were unchanged.
- Native Debian 13 / Python 3.13.5 QA: **337 passed**; Ruff lint and formatting passed in isolated
  `/var/tmp/forex-issue30-qa-v8kDmhxa`, with a separate test venv and no production `.env`.
  Development dependencies were not installed into the service environment.
- HTTPX fake-token regression cases pass at INFO and DEBUG; transport log levels are capped at
  WARNING. No real credentials or provider requests were used in those tests.
- Local disposable SQLite/Bash checks cover WAL backup, restoration of existing/missing/corrupt
  targets, preservation of old bytes, and invalid source rejection before mutation. The VPS drill
  separately establishes native permissions and service-user readability.
- Local review found no outstanding actionable findings. The restore-permission finding was fixed and verified on the VPS. Independent external review was not performed.

## Remaining validation

The deployment is complete and live delivery is enabled. The first naturally qualifying candidate reaching Telegram remains unverified in this record. The successful connectivity message, separate provider checks, and No Alert runs do not establish that path.

Issue #32 was closed as not planned, without completing its remaining checks. Use the [live monitoring procedure](vps-deployment.md#inspect-live-operation) to inspect future runs and preserve actual delivery evidence. This document is a dated verification record, not a live uptime report.
