# Build Quality Recommendations

Date: August 6, 2026

## Recommended Codex Skills

Use these skills as the normal working loop:

- `github:github` for issue/repo orientation and issue hygiene.
- `github:yeet` when committing, pushing, and opening pull requests.
- `tdd` for strategy, scoring, scheduling, and parsing work where edge cases matter.
- `compound-engineering:ce-work` for executing one GitHub issue end-to-end.
- `diagnosing-bugs` when market data, scheduling, Telegram, or LLM calls behave strangely.
- `code-review` before merging larger chunks.
- `research` when choosing APIs, VPS/deployment patterns, market data providers, or LLM providers.
- `codebase-design` when the architecture starts feeling tangled.
- `domain-modeling` before implementing signal/scoring objects, because this project needs clean concepts like `CandidateSignal`, `NewsImpact`, `AlertDecision`, and `RunLog`.
- `obsidian-vault` only when updating the local vault context notes.

Use these only when needed:

- `request-refactor-plan` if the code gets messy after v1.
- `setup-pre-commit` once there is actual code to lint/test.
- `compound-engineering:ce-debug` for stubborn production-ish failures.
- `compound-engineering:ce-code-review` for a stricter review pass before deploying.

## Plugins Worth Considering

Already useful:

- GitHub: installed and already used for the repo and issues.

Maybe later:

- Sentry: useful after VPS deployment if runtime errors start mattering.
- Sentry cron monitors: useful if missed or failing scheduled jobs become painful.
- Codex Security: useful before the repo grows or if secrets/config handling gets more complex.
- OpenAI Developers: only useful if the project switches from Ollama Cloud to OpenAI APIs.

Skip for now:

- Supabase/Postgres plugins, because SQLite is enough for v1.
- PostHog, because this is not a user-facing product yet.
- Slack/Gmail/Calendar/Notion, because they do not improve the core bot.

## Engineering Priorities

1. Make the bot observable before making it clever.
2. Keep strategy logic deterministic and testable.
3. Keep the LLM isolated to news sentiment, with strict JSON validation.
4. Log every run, candidate signal, LLM input/output, alert decision, and error.
5. Add cooldown/dedupe early to avoid spam.
6. Fail closed when data, news, or LLM calls are unavailable.
7. Keep deployment boring: one Python service, one SQLite DB, one systemd service.
8. Add `pytest`, `ruff`, and GitHub Actions early so AI-generated changes get checked automatically.
9. Use SQLite WAL mode and busy timeouts once scheduled logging starts writing frequently.

## Research Notes

APScheduler is a good fit because it is designed to run Python callables on recurring schedules and supports cron-style triggers for specific times of day. It also has misfire/concurrency controls that matter for a bot that should not stack overlapping runs.

Source: https://apscheduler.readthedocs.io/en/master/userguide.html

Telegram's Bot API is HTTP-based and supports sending messages through `sendMessage`, so the notifier can be a small `httpx` wrapper instead of a large bot framework.

Source: https://core.telegram.org/bots/api

Ollama Cloud should be called remotely from the VPS using an API key; local Ollama does not need authentication, but cloud model access via `ollama.com` does.

Source: https://docs.ollama.com/api/authentication

Do not assume Ollama Cloud will enforce strict structured output the same way local Ollama can. For v1, prompt for JSON, validate with Pydantic, retry once, then mark news sentiment unavailable if parsing still fails.

Sources:

- https://docs.ollama.com/capabilities/structured-outputs
- https://docs.ollama.com/api/generate

For deployment, `systemd` with `Restart=on-failure` is appropriate for a long-running service, and rate limiting should be configured so a broken bot does not restart forever.

Source: https://www.man7.org/linux/man-pages/man5/systemd.service.5.html

Use `EnvironmentFile` or equivalent systemd environment handling for secrets on the VPS instead of hardcoding keys in service files or source code.

Source: https://www.man7.org/linux/man-pages/man5/systemd.exec.5.html

Add automated checks:

- `pytest` for indicators, strategy rules, scoring, JSON parsing, and cooldown behavior.
- `ruff` for linting and formatting.
- GitHub Actions for `pytest` and `ruff` on pushes and pull requests.

Sources:

- https://docs.pytest.org/en/stable/
- https://docs.astral.sh/ruff/linter/
- https://docs.astral.sh/ruff/formatter/
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

If production reliability starts to matter, Sentry can capture Python exceptions and cron monitors can track missed/failing scheduled jobs.

Sources:

- https://github.com/getsentry/sentry-python
- https://docs.sentry.io/product/crons/

SQLite WAL mode can improve read/write behavior for a small logging database, and busy timeouts help reduce transient lock failures.

Sources:

- https://www.sqlite.org/wal.html
- https://www.sqlite.org/c3ref/busy_timeout.html

Reddit/community signal was consistent with boring production advice: self-hosting threads repeatedly emphasize backups, avoiding unnecessary management layers, and not overcomplicating small services; trading/algotrading threads are skeptical of indicator-only systems, which reinforces the need for logging, backtesting, and visible reasons rather than blind signal worship.

Sources:

- https://fi.reddit.com/r/selfhosted/comments/1salkni/laugh_at_my_pain_and_learn_from_my_mistakes/
- https://zh.reddit.com/r/algotrading/comments/alavg1/do_technical_analysis_work/
- https://hr.reddit.com/r/Forex/comments/haphhb/an_indicator_to_show_overunder_bought_or_sold/
- https://fr.reddit.com/r/algotrading/comments/1e40bak/to_people_currently_running_a_live_strategy_whats/
