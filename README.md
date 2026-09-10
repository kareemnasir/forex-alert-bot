# Forex Alert Bot

A hobby Forex alerting bot that runs on Debian 13 on DigitalOcean, checks technical setups, analyzes recent news sentiment with an LLM API, and sends Telegram alerts. It does not connect to broker accounts and does not execute trades.

## V1 Goal

Build a scheduled Python service that:

- runs every 30-60 minutes during the configured alert window
- fetches Forex candle data
- evaluates Trend Pullback, Breakout, and Mean Reversion strategy modules
- uses Ollama Cloud to analyze recent news sentiment when a candidate setup exists
- combines strategy candidates through one scoring layer
- sends clear Telegram alerts
- logs runs, candidate signals, news analyses, and final alerts to SQLite

## Architecture

```text
Debian 13 on DigitalOcean: Python app
  -> scheduler or operator starts one signal check
  -> fetch forex candles
  -> calculate technical indicators
  -> run strategy modules
  -> generate candidate signals
  -> score technical agreement and conflict
  -> fetch recent news when a setup is present
  -> call Ollama Cloud for structured sentiment
  -> apply deterministic news score adjustment
  -> dedupe/cooldown alerts
  -> send Telegram alert
  -> save logs to SQLite
```

## Docs

- [Project Context](docs/project-context.md)
- [Issue Plan](docs/issue-plan.md)
- [Debian 13 on DigitalOcean Deployment](docs/vps-deployment.md)

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
```

Configuration is read from `.env` and environment variables. Explicit environment variables take
precedence over values in `.env`.

## One-shot runs

Execute exactly one complete signal check in dry-run mode, then exit:

```bash
python -m forex_alert_bot --run-once --dry-run
```

The command uses the same `SignalPipeline` path as scheduled execution. It persists the Run,
Candidate Signals, News Analyses, technical and final Alert Decisions, Score Adjustments, skips,
Alerts, and Error Records that occur. Operator output includes the Run ID, final status, and counts
for candidates, technical decisions, final decisions, and sent alerts.

Without the command-line override, one-shot execution honors the configured `DRY_RUN` value:

```bash
python -m forex_alert_bot --run-once
```

Keep `DRY_RUN=true` until live Telegram delivery has been intentionally enabled and verified.

## Scheduled runs

Start the recurring service with an explicit command-line safety override:

```bash
python -m forex_alert_bot --schedule --dry-run
```

It runs at :00 and :30 during the configured local alert window (7:00 AM through
10:00 PM in `America/Detroit` by default), intersected with the V1 Forex week: Sunday from
5:00 PM, Monday through Thursday for the full configured window, and Friday through 5:00 PM.
Saturday is excluded. The equivalent configured dry-run service is:

```bash
DRY_RUN=true python -m forex_alert_bot --schedule
```

`DRY_RUN=true` is persistent runtime configuration for both one-shot and scheduled execution.
`--dry-run` is a one-way safety override: it forces dry-run mode even when configuration is live,
but it can never force live delivery. The override is accepted only with `--run-once` or
`--schedule`.

The owner authorized live Telegram delivery on September 10, 2026. The deployed VPS uses
`DRY_RUN=false` and the live systemd override; issue #32 tracks ongoing live monitoring.
The dry-run commands above remain available for explicit preflight checks. See the [Debian 13 on DigitalOcean deployment guide](docs/vps-deployment.md) for
the repository-controlled systemd unit, persistent paths, backup/restore, and update procedures.

Each scheduled run is saved to SQLite. By default, the database is created at
`data/forex-alert-bot.sqlite3`; set `DATABASE_PATH` to use another local path. The
database keeps runs, candidate signals, technical and final decisions, news-analysis
input/output, score adjustments, delivery skips, sent alerts, and errors so every
outcome can be inspected back to its source data.

## Operator inspection

Read the 10 most recent Runs without initializing, migrating, or otherwise changing SQLite:

```bash
python -m forex_alert_bot --inspect-recent
```

Inspect one Run and its Error Records, Candidate Signals, News Analyses, technical/final Alert
Decisions, Score Adjustments, cooldown skips, delivery skips, and sent-Alert references:

```bash
python -m forex_alert_bot --inspect-run 42
```

Inspection omits complete provider/LLM payloads, fingerprints, and formatted message bodies. A
missing database or unknown Run ID is reported clearly; an initialized database with no Runs
prints `No recorded runs.`

## Command and exit behavior

- With no command, the app performs no signal check and exits successfully after explaining the
  available commands.
- `--telegram-test`, `--run-once`, `--schedule`, `--inspect-recent`, and `--inspect-run` are mutually
  exclusive. Incompatible combinations and invalid `--dry-run` usage exit with status 2.
- A successful one-shot or inspection command exits with status 0. A failed one-shot, missing
  inspection database, unknown Run ID, or Telegram test failure exits with status 1.
- `--schedule` is the long-running command and does not exit after one Run.

## Alert cooldown

Set `ALERT_COOLDOWN_MINUTES` to control how long a sent alert suppresses another alert
for the same pair, direction, timeframe, alert level, and contributing strategy set. The
default is 120 minutes; set it to `0` to disable the cooldown.

The cooldown service checks fingerprinted sent-alert history before delivery. A blocked
duplicate is saved in the SQLite `alert_skips` table with the matching alert ID and reason,
so skipped decisions remain inspectable. Dry-run and delivery skips are saved separately
with their formatted message and final decision link.

## Market data

The first provider is Twelve Data. Create an API key, then set `MARKET_DATA_API_KEY` in
`.env`. Configure the comma-separated `MARKET_DATA_PAIRS` and `MARKET_DATA_TIMEFRAMES`
values as needed. The defaults fetch `EUR/USD`, `GBP/USD`, and `USD/JPY` on `15min` and
`1h` timeframes. Candles are normalized to UTC with timestamp, open, high, low, close,
and an optional volume value.

Set `TECHNICAL_STRATEGIES` to a comma-separated subset of `trend-pullback`, `breakout`,
and `mean-reversion`. These deterministic Python strategies are the only components that
can create candidate signals.

Provider failures, rate limits, missing data, and malformed responses do not stop the
scheduler. They are recorded as `market-data` errors in the SQLite run log.

## News

Marketaux is the first news provider. Set `NEWS_API_KEY` in `.env`, and configure
`NEWS_MAX_AGE_HOURS` and `NEWS_MAX_ITEMS` to control the recent article window and
returned item cap. A scheduled run requests news only after technical candidates exist,
and only for candidate pairs. It then filters stale or irrelevant articles and normalizes
relevant results to UTC with source, URL/snippet, and pair/currency metadata.

Missing credentials, empty results, provider errors, and malformed articles do not stop
the scheduler. Recoverable provider failures are recorded as `news` errors.

## Ollama Cloud sentiment

Set `OLLAMA_API_KEY` and `OLLAMA_MODEL` to analyze normalized news through Ollama Cloud.
`OLLAMA_HOST` defaults to `https://ollama.com`; timeout, headline cap, and retry budget are
configurable with `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_MAX_HEADLINES`, and
`OLLAMA_RETRY_COUNT`. Leave the model configurable because the models available to an
Ollama Pro account can change.

The sentiment service is called only when candidate-scoped news exists. It sends only
articles relevant to the requested pairs, asks for JSON, then validates the model content
locally. Invalid responses and provider failures retry within the configured budget and
produce an inspectable unavailable result rather than an exception.

Ollama returns news-impact objects only. A deterministic Python policy applies bounded
support boosts, contradiction reductions or suppression, and high-risk reductions or
suppression. News cannot create a candidate, direction, or alert from a technical
`No Alert`, and final scores are clamped to 0-100.

## Telegram test

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (or as explicit environment
variables), then send exactly one test message:

```bash
python -m forex_alert_bot --telegram-test
```

The command reports missing credentials and Telegram API failures clearly, and it does not
run any signal checks or place trades.

## Checks

```bash
python -m pytest
ruff check .
ruff format --check .
```

Tests that initialize SQLite or execute the pipeline always use temporary database paths. The
complete test suite guards `data/forex-alert-bot.sqlite3` and its sidecars against creation or
modification.
