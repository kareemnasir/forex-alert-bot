# Implementation milestones

Updated September 10, 2026. [Project overview](../README.md)

The core implementation and deployment are complete. GitHub issues and pull requests preserve the work behind each milestone.

| Milestone | Completed work | Issues |
| --- | --- | --- |
| Foundation | Package, configuration, Telegram test, scheduler, SQLite | #16–#19 |
| Technical analysis | Market data, indicators, three strategies | #20–#24 |
| Decisions and delivery | Shared scoring, message formatting, cooldown | #25–#27 |
| News context | Marketaux retrieval and Ollama sentiment | #28–#29 |
| Integration and verification | Pipeline, CI, operator CLI | #47, #31, #50 |
| Deployment | Debian/systemd service, recovery procedures, live activation | [#30](https://github.com/kareemnasir/forex-alert-bot/issues/30), [PR #53](https://github.com/kareemnasir/forex-alert-bot/pull/53) |

## Remaining validation

The recorded deployment evidence includes successful scheduled No Alert runs and a Telegram connectivity test. A naturally qualifying candidate passing through news analysis, scoring, cooldown, and Telegram delivery remains unverified in that evidence. This is a coverage gap, not a reason to manufacture a signal.

[Issue #32](https://github.com/kareemnasir/forex-alert-bot/issues/32) was closed as not planned on September 10, 2026. Its unfinished checks were not marked complete. There are no open implementation issues at this snapshot.

## Possible future work

Backtesting, an economic-calendar filter, provider fallback, and a read-only dashboard are possible extensions. They are not implemented or committed roadmap items. Strategy changes should be based on observed evidence and regression checks.
