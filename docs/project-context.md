# Architecture and scoring rules

[Back to the project overview](../README.md)

The bot runs one signal pipeline from either the scheduler or the command line. Technical strategies create candidates, deterministic policies score them, and Telegram delivers qualifying decisions. SQLite preserves the inputs and outcomes needed to inspect each run.

## Components

| Component | Responsibility |
| --- | --- |
| `market_data.py` | Retrieve Twelve Data candles and normalize timestamps and OHLC values. |
| `indicators.py` | Calculate EMA 20/50/200, RSI, ATR, and ADX in Python. |
| `strategies.py` | Evaluate trend pullback, breakout, and mean-reversion rules. |
| `scoring.py` | Group candidates by pair/timeframe and resolve agreement or conflict. |
| `news.py` / `sentiment.py` | Retrieve relevant Marketaux articles and validate Ollama news analysis. |
| `news_adjustment.py` | Apply bounded score changes or suppress an existing decision. |
| `cooldown.py` / `telegram.py` | Check sent-alert history and deliver qualifying messages. |
| `database.py` / `inspection.py` | Write decision records and expose read-only operator reports. |
| `pipeline.py` / `scheduler.py` / `cli.py` | Connect the stages and provide scheduled/manual entry points. |

## Technical strategies

**Trend pullback** uses the highest configured timeframe for EMA 50/200 trend confirmation. On a lower timeframe, the previous candle must touch the EMA 20/50 zone within an ATR tolerance; RSI and the latest close must recover in the trend direction. Its default candidate score is 70.

**Breakout** compares the latest close with the preceding 20-candle high or low. Candle-body and extension filters use ATR. Its default candidate score is 68.

**Mean reversion** looks for a close near a range edge, an extreme or recovering RSI, ADX at or below 25, and bounded volatility relative to the range. Its default candidate score is 65.

Each candidate includes a direction, reasons, and an invalidation level for manual review. Strategy thresholds live in validated configuration dataclasses; the environment selects which strategies run.

## Technical scoring

Candidates are grouped by pair and timeframe. For each direction, the scorer takes the highest candidate score and adds 10 points for each additional distinct supporting strategy. It selects the stronger direction and subtracts half the opposing direction's score, rounded up. Equal opposing scores suppress the alert.

| Final score | Level |
| --- | --- |
| 80–100 | Strong Watch |
| 65–79 | Watch |
| 50–64 | Weak Watch |
| Below 50 | No Alert |

Scores are rule outputs, not calibrated probabilities of a successful trade.

## News analysis and adjustment

News is requested for pairs with a technical decision that has a direction. Articles are filtered by relevance and age before being sent to Ollama Cloud. The analyzer validates JSON fields, pair coverage, strength bounds, and risk levels. Invalid responses and eligible provider failures retry within the configured budget, then return an unavailable result.

The default Python policy:

- Adds up to 10 points for supporting news, proportional to strength.
- Subtracts up to 20 points for contradicting news; contradiction strength of at least 0.75 suppresses the alert.
- Subtracts 15 points for high-risk news; high risk combined with major news risk suppresses the alert.
- Clamps final scores to 0–100. Combined penalties can exceed 20 points.
- Leaves the technical score unchanged when news is unavailable, absent, uncertain, or neutral, and adds an explanation.

News cannot create a candidate, change its direction, or promote a technical No Alert into a qualifying alert. A missing news service does not automatically prevent delivery of an otherwise qualifying technical decision.

## Persistence and delivery

The pipeline records candidates, technical/final decisions, news input/output, adjustments, errors, and delivery outcomes. A No Alert run is also recorded. Inspection opens the database read-only and omits raw provider payloads, fingerprints, and message bodies.

The cooldown defaults to 120 minutes and matches pair, direction, timeframe, alert level, and contributing strategy set. Only sent alerts establish cooldown history. Dry-run decisions are recorded as delivery skips and do not count as sent alerts.

Recoverable provider or delivery errors can coexist with a completed run. Check error records when assessing health. SQLite uses WAL mode, foreign keys, and a busy timeout; tests use separate temporary databases.

## Deployment lessons

HTTP request logging can expose credentials embedded in provider URLs. The application caps HTTPX and HTTPCore logging at WARNING, with regression tests using fake tokens at INFO and DEBUG levels.

A SQLite restore that succeeds as root does not establish that the service can read it. The deployment drill restores into a separate directory, checks integrity and logical content, then inspects the restored records as the service user. Source, configuration, and runtime data are stored separately so rolling back code preserves the database.

## Scheduling

Defaults are `America/Detroit`, every half hour from 07:00 through 22:00, intersected with Sunday from 17:00 through Friday at 17:00. Saturday is excluded. The end-hour trigger is at `:00`; no `:30` run follows it.

`create_scheduler(settings)` builds these triggers, limits the job to one concurrent instance, and coalesces missed executions. Starting the scheduler does not immediately run a check. One-shot commands bypass the schedule. The weekly policy has no holiday or broker-specific calendar.

## Scope

The current application supports Telegram monitoring and manual review. It has no broker integration, order execution, position tracking, exit alerts, email delivery, dashboard, or backtesting. Adding those would require separate design and validation.
