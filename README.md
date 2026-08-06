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
