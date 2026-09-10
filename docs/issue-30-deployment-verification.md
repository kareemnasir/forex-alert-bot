# Issue #30 deployment verification

Date: September 10, 2026. Status: **deployment acceptance verified; service running in dry-run**.
Source of truth: [issue #30](https://github.com/kareemnasir/forex-alert-bot/issues/30).
Changes and evidence: [draft PR #53](https://github.com/kareemnasir/forex-alert-bot/pull/53).
Dependencies #47, #31 and #50 are closed. Issue #30 remains open for the user's review.

## Host and deployed revision

- DigitalOcean Droplet `forex-alert-bot`, ID `599406664`, `nyc1`, IPv4 `147.182.139.12`.
- Debian GNU/Linux 13 (trixie), Debian version 13.5; Python 3.13.5; systemd 257.13.
- SSH port 22, root UID 0; administrative access verified after the operator unlocked the local key.
- Pinned ED25519 host fingerprint: `SHA256:MKsvP2lDgmH1STyESUqAPYagJ3X1nyKz6ZbK8uSwN/g`.
  This was first-use trust, followed by strict host-key checking. Authenticated hostname and
  DigitalOcean link-local metadata matched the supplied host; no independent console fingerprint
  attestation was obtained.
- Deployed application revision: `4d81a389500122269b23b2d023e1b09cdfcdcd18`.
  Later documentation-only commits in PR #53 are not claimed as the running application revision.
- The initial host had no existing bot installation, service user, or database. Local runtime
  history and the unrelated `codex/digitalocean-debian-docs` branch were preserved.

A Git bundle transferred the committed repository over SSH; no workstation private key or GitHub
credential was installed on the VPS. The checkout is detached, root-owned and service-readable at
`/opt/forex-alert-bot`. The runbook now documents bundle-based updates for this private repository.

## Acceptance evidence

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

## Installed unit definition

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

## Run evidence

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
decision. Neither manual Run counts toward #32's scheduled-run total.

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
#30; carry this coverage gap into #32.

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
The one-shot command is evidence of what ran; do not rerun it inside #32's observation period.

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
- Review is local and sequential in the main agent context, per repository workflow instructions.
  The earlier external-review attempt was rejected before starting; it was not retried and no
  independent external review is claimed. Final local review found no outstanding actionable
  findings; the prior restore-permission finding was verified fixed on the VPS.

## Begin issue #32

The formal observation period has not started. Leave the service in dry-run and follow
[the exact observation procedure](vps-deployment.md#begin-the-32-observation-period):

1. Review #30's completed deployment evidence, including natural scheduled Run 3. No deployment
   acceptance check remains blocked; #30 and draft PR #53 remain open for the user's review.
2. Stop the service, confirm inactive, make and validate a fresh timestamped online backup using
   runbook section 8, and retain it as the deployment archive. Keep the original database.
3. Record the UTC start boundary and `SELECT coalesce(max(id),0) FROM runs;` as `BASELINE_RUN_ID`.
4. Verify external `DRY_RUN=true` and literal `--schedule --dry-run`; start the service and record
   start time, enabled state and status. No manual one-shots during the observation window.
5. Collect at least **three trading days and 50 provider-successful scheduled Runs** after the
   baseline. Correlate Run IDs with journal trigger times, inspect every outcome category, and
   separate provider failures from strategy findings. Preserve history and keep automated tests
   isolated from the runtime database.
6. Report natural-candidate coverage honestly and conclude `remain in dry-run` or
   `ready for limited live alerts`. Neither conclusion itself authorizes sending messages.
