# Forex Alert Bot

A hobby Forex alerting bot that runs on a VPS, checks technical setups, analyzes recent news sentiment with an LLM API, and sends Telegram alerts. It does not connect to broker accounts and does not execute trades.

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
VPS Python app
  -> scheduler wakes every 30-60 minutes
  -> fetch forex candles
  -> calculate technical indicators
  -> run strategy modules
  -> generate candidate signals
  -> fetch recent news when a setup is present
  -> call Ollama Cloud for structured sentiment
  -> score agreement, conflict, and news confirmation
  -> dedupe/cooldown alerts
  -> send Telegram alert
  -> save logs to SQLite
```

## Docs

- [Project Context](docs/project-context.md)
- [Issue Plan](docs/issue-plan.md)

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

```bash
python -m forex_alert_bot --dry-run
```

The scaffold logs that dry-run mode is active and does not perform any signal checks or send alerts.

## Scheduled runs

Start the recurring signal-check service with:

```bash
python -m forex_alert_bot --schedule
```

It runs at :00 and :30 during the configured local alert window (7:00 AM through
10:00 PM in `America/Detroit` by default). Set `DRY_RUN=true` to prevent real alerts;
market-data fetches still run so the configured provider can be checked safely.

Each scheduled run is saved to SQLite. By default, the database is created at
`data/forex-alert-bot.sqlite3`; set `DATABASE_PATH` to use another local path. The
database keeps runs, candidate signals, news-analysis input/output, sent alerts, and
errors so future alerts can be inspected back to their source data.

## Alert cooldown

Set `ALERT_COOLDOWN_MINUTES` to control how long a sent alert suppresses another alert
for the same pair, direction, timeframe, alert level, and contributing strategy set. The
default is 120 minutes; set it to `0` to disable the cooldown.

The cooldown service checks fingerprinted sent-alert history before delivery. A blocked
duplicate is saved in the SQLite `alert_skips` table with the matching alert ID and reason,
so skipped decisions remain inspectable. This policy layer does not send Telegram messages;
a future delivery workflow can call it immediately before sending.

## Market data

The first provider is Twelve Data. Create an API key, then set `MARKET_DATA_API_KEY` in
`.env`. Configure the comma-separated `MARKET_DATA_PAIRS` and `MARKET_DATA_TIMEFRAMES`
values as needed. The defaults fetch `EUR/USD`, `GBP/USD`, and `USD/JPY` on `15min` and
`1h` timeframes. Candles are normalized to UTC with timestamp, open, high, low, close,
and an optional volume value.

Provider failures, rate limits, missing data, and malformed responses do not stop the
scheduler. They are recorded as `market-data` errors in the SQLite run log.

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
