# Project Context

Date: August 6, 2026

## Summary

Build a hobby Forex alerting tool. The software does not connect to a broker account and does not execute trades. It runs on a VPS, checks market/news conditions on a schedule, and sends Telegram or email alerts such as `BUY Watch`, `SELL Watch`, `Exit Watch`, or `No Trade`.

The system should be inspectable and logged. Python rules make the trading decision. The LLM only analyzes recent news sentiment.

## Current Direction

- Run the app on a cheap CPU VPS.
- Use the same VPS for the scheduler, data fetching, strategy logic, logging, and Telegram/email alerts.
- Do not run the LLM locally on the VPS.
- Use Ollama Cloud through the existing Ollama Pro plan for news sentiment.
- Avoid OpenRouter for v1 unless Ollama Cloud limits, model catalog, or quality become blockers.
- Use SQLite first for logs and signal history.
- Add Docker later if useful, but do not overbuild v1.

## Runtime Schedule

Target schedule:

- Run every 30 minutes to 1 hour.
- Active alert window: around 7:00 AM to 10:00 PM local time.
- Timezone: `America/Detroit`.
- Forex-specific note: forex is roughly 24/5, so Sunday evening through Friday evening may make more sense than every calendar day.

Example APScheduler shape:

```python
scheduler.add_job(
    run_signal_check,
    trigger="cron",
    minute="0,30",
    hour="7-22",
    timezone="America/Detroit",
)
```

## Architecture

```text
VPS Python app
  -> scheduler wakes every 30-60 minutes
  -> fetch forex candles
  -> calculate technical indicators
  -> run v1 strategy modules
  -> generate candidate signals
  -> fetch recent relevant news when a setup is present
  -> call Ollama Cloud for structured news sentiment
  -> score strategy agreement, conflict, and news confirmation
  -> dedupe/cooldown alerts
  -> send Telegram/email alert
  -> save run logs, candidate signals, final alerts, and LLM input/output
```

## Design Rule

The LLM is not the trading brain.

Use:

```text
Technical rules decide possible BUY / SELL / NO TRADE.
LLM decides whether recent news supports, contradicts, or increases risk.
Python combines the result and sends the final alert.
```

This keeps the system debuggable and prevents the model from hallucinating trades.

## V1 Strategy Modules

V1 includes four modules, but they should not each send alerts independently. Each module generates candidate signals. A single scoring layer decides whether the final output is `Strong Watch`, `Watch`, `Weak Watch`, or no alert.

```text
Trend Pullback
Breakout
Mean Reversion
News Sentiment
        -> Signal Scorer
        -> Alert / No Alert
```

### 1. Trend Pullback

Best for normal trending Forex conditions.

Buy candidate:

```text
1h EMA 50 > EMA 200
15m price pulls back toward EMA 20/50
15m RSI dips, then recovers
price closes back in trend direction
```

Sell candidate:

```text
1h EMA 50 < EMA 200
15m price pulls back upward toward EMA 20/50
15m RSI bounces, then weakens
price closes back in trend direction
```

Useful indicators:

- EMA 20
- EMA 50
- EMA 200
- RSI
- ATR

### 2. Breakout

Best when a pair breaks out of a recent range during active sessions.

Buy candidate:

```text
price closes above recent 20-candle high
breakout candle body is meaningful
ATR confirms enough movement
price is not already too extended
```

Sell candidate:

```text
price closes below recent 20-candle low
breakout candle body is meaningful
ATR confirms enough movement
price is not already too extended
```

Add cooldown after a breakout so the bot does not send repeated alerts on every candle.

### 3. Mean Reversion

Best for sideways or choppy markets. Do not use when the market is clearly trending.

Buy candidate:

```text
market regime is ranging
price is near recent support/lower band
RSI is oversold or recovering from oversold
ATR is not exploding
```

Sell candidate:

```text
market regime is ranging
price is near recent resistance/upper band
RSI is overbought or rolling over from overbought
ATR is not exploding
```

Possible range detector:

```text
EMA 50 and EMA 200 are close together
ADX is low
recent highs/lows are contained
```

### 4. News Sentiment

News is a confirmation/risk module, not a standalone trade generator.

```text
Technical BUY + news bullish for pair = boost score
Technical BUY + news bearish for pair = reduce/block score
Technical SELL + news bearish for pair = boost score
Technical SELL + news bullish for pair = reduce/block score
No technical setup + strong news = optional News Watch, not trade alert
```

## Signal Scoring

Suggested scoring model:

```text
Technical strategy score: 0 to 80
News adjustment: -20 to +20
Final score: 0 to 100
```

Suggested alert thresholds:

```text
80-100 = Strong Watch
65-79 = Watch
50-64 = Weak Watch
Below 50 = no alert
```

Agreement/conflict rules:

```text
Trend Pullback BUY + Breakout BUY = stronger signal
Trend Pullback BUY + News bullish = stronger signal
Trend Pullback BUY + Mean Reversion SELL = conflict, usually skip
Breakout BUY + News bearish = lower score or block
Any high-impact news risk = warn or skip depending on config
```

## Suggested Tech Stack

- Python 3.12+
- `pandas` for candle data
- `ta` for indicators
- `httpx` for API calls
- `APScheduler` for scheduled runs
- SQLite for v1 storage
- Telegram Bot API for alerts
- Optional: email via SMTP or transactional email provider
- Optional later: Docker + systemd service

## LLM Setup

Use Ollama Cloud from the VPS.

```env
OLLAMA_API_KEY=...
OLLAMA_HOST=https://ollama.com
OLLAMA_MODEL=...
OLLAMA_TIMEOUT_SECONDS=30
OLLAMA_MAX_HEADLINES=10
OLLAMA_RETRY_COUNT=1
```

The app calls Ollama Cloud over HTTPS. The model runs remotely on Ollama infrastructure, not on the VPS.

Provider abstraction should be simple so the app can later swap to DeepSeek, Qwen, Kimi, OpenAI, Gemini, or OpenRouter without rewriting the rest of the bot.

## LLM News Analysis Contract

Input to LLM:

- selected pairs
- recent headlines/articles
- source
- publish time
- optional detected currencies/entities

Output from LLM should be strict JSON only.

Example output:

```json
{
  "pair_impacts": [
    {
      "pair": "EUR/USD",
      "direction": "bullish",
      "strength": 0.42,
      "risk_level": "medium",
      "summary": "Recent headlines mildly favor EUR over USD, but evidence is not strong."
    }
  ],
  "major_news_risk": false
}
```

Prompt rules:

- Return JSON only.
- Analyze news sentiment, not trade entries.
- Do not recommend trades.
- Use only provided headlines/articles.
- If evidence is weak, use low confidence.
- Mark uncertainty clearly.

## Alert Format

Example Telegram alert:

```text
EUR/USD SELL Watch
Timeframe: 15m
Price: 1.0924
Technical Score: 71/100
News Impact: Bearish EUR/USD, 0.55 strength
Confidence: 68/100
Reason: EMA trend down, RSI rejection, news modestly favors USD.
Invalidation: above 1.0960
Review Window: next 3 candles
Manual decision only.
```

Prefer:

- `BUY Watch`
- `SELL Watch`
- `Exit Watch`
- `No Trade`

## V1 Scope

Build in v1:

- scheduler
- Telegram notifier
- market data fetcher
- technical indicators
- Trend Pullback module
- Breakout module
- Mean Reversion module
- news fetcher
- Ollama Cloud sentiment module
- shared scoring layer
- strategy agreement/conflict handling
- SQLite logging
- dry-run mode
- dedupe/cooldown logic

Later:

- backtesting
- economic calendar filter
- richer dashboard
- provider fallback
- more advanced position/risk notes

## Key Guardrails

- No broker connection.
- No trade execution.
- No storage of broker credentials.
- Log every alert and every LLM response.
- Do not alert repeatedly for the same pair/direction without cooldown.
- Fail closed: if APIs break or news analysis fails, either skip alert or mark news as unavailable.
- Keep strategy rules configurable.
- Use dry-run mode before sending real alerts.

## Open Questions

- Which pairs should v1 monitor?
- Should alerts run Monday-Friday only, or Sunday evening-Friday evening?
- Which timeframe should lead for each strategy: 15m, 30m, 1h, or multiple?
- Telegram only for v1, or email too?
- Which market-data API has acceptable pricing/limits?
- Which Ollama Cloud model should be used for sentiment?
- What score thresholds should be used for Strong Watch, Watch, and Weak Watch?
- Should strong news without technical confirmation create a `News Watch`, or only affect technical alerts?
