# Issue Plan

Use these issues to build the project in small, reviewable chunks.

## MVP 1: Foundation

### Project scaffold

Create the Python package layout, config loading, `.env.example`, logging setup, and a basic CLI entrypoint.

Acceptance criteria:

- package imports cleanly
- app can run in dry-run mode
- config and env values are loaded predictably
- README has setup instructions

### Telegram alert test

Implement a Telegram notifier and send a single test message.

Acceptance criteria:

- bot token and chat ID are read from environment variables
- test command sends one message
- failures return clear error messages

### Scheduler

Run the signal check every 30 minutes during the configured alert window.

Acceptance criteria:

- timezone is configurable
- default timezone is `America/Detroit`
- default active window is 7 AM to 10 PM
- dry-run mode logs scheduled runs

## MVP 2: Market Data And Technicals

### Market data integration

Fetch and normalize candle data for configured Forex pairs/timeframes.

Acceptance criteria:

- supports at least one provider
- returns normalized OHLCV-like data
- handles provider errors and rate limits
- does not crash the scheduler on fetch failure

### Indicators

Compute the indicators needed by v1 strategies.

Acceptance criteria:

- EMA 20, EMA 50, EMA 200
- RSI
- ATR
- ADX or range-detection substitute
- tests or sample fixtures verify expected output shape

### Trend Pullback strategy

Generate candidate buy/sell signals for trend pullbacks.

Acceptance criteria:

- uses higher-timeframe trend confirmation
- uses lower-timeframe pullback/recovery logic
- returns score, direction, reason fields, and invalidation level

### Breakout strategy

Generate candidate buy/sell signals for range breakouts.

Acceptance criteria:

- detects recent range highs/lows
- validates breakout candle quality
- uses ATR/extension filters
- includes cooldown-friendly metadata

### Mean Reversion strategy

Generate candidate buy/sell signals for ranging markets.

Acceptance criteria:

- detects range/chop conditions
- avoids obvious trending regimes
- uses support/resistance or band logic
- returns clear reasons

## MVP 3: Scoring And News

### Signal scorer

Combine strategy candidates, handle agreement/conflict, and assign final score.

Acceptance criteria:

- boosts agreement between same-direction candidates
- detects conflict between opposing candidates
- applies thresholds for Strong Watch, Watch, Weak Watch, and no alert
- returns a final alert decision object

### News fetcher

Pull recent relevant Forex/macro headlines.

Acceptance criteria:

- fetches recent news for configured currencies/pairs
- stores source and publish time
- filters stale or irrelevant items
- degrades gracefully when no news is available

### Ollama Cloud sentiment

Analyze news through Ollama Cloud and parse strict JSON sentiment.

Acceptance criteria:

- uses `OLLAMA_API_KEY`
- sends only relevant headlines/articles
- validates the model response shape
- marks sentiment unavailable on invalid JSON or API failure

### Final alert formatting

Format final Telegram alerts with score, strategy, reason, news impact, and invalidation.

Acceptance criteria:

- message fits comfortably in Telegram
- includes pair, direction, timeframe, score, reasons, and manual-decision reminder
- avoids duplicate/spammy messages

## MVP 4: Persistence And Deployment

### SQLite logging

Save runs, candidate signals, news analyses, final alerts, and errors.

Acceptance criteria:

- database initializes automatically
- all scheduled runs are logged
- sent alerts can be traced back to candidates and news input/output

### Dedupe and cooldown

Prevent repeated alerts for the same pair/direction/setup.

Acceptance criteria:

- cooldown duration is configurable
- duplicate checks use recent alert history
- skipped duplicates are logged

### VPS deployment

Document and implement VPS deployment using a systemd service.

Acceptance criteria:

- setup instructions for Ubuntu VPS
- service restarts on failure
- logs are inspectable
- `.env` is not committed
