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
cp .env.example .env
```

The first implementation should support dry-run mode before any live Telegram alerts are sent.
