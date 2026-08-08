# Forex Alerting

The Forex Alerting context describes the records the bot keeps so every manual-decision
alert can be understood after it was sent.

## Language

**Run**:
One scheduled attempt to evaluate the configured market conditions, with a completed or
failed outcome.
_Avoid_: Job, execution

**Candidate Signal**:
A possible BUY, SELL, or other watch outcome emitted by one technical strategy during a
run.
_Avoid_: Trade, alert

**Invalidation Level**:
The market price beyond which a candidate signal's setup no longer holds. It is context
for a manual decision, not an order placed with a broker.
_Avoid_: Stop-loss order, trade exit

**News Analysis**:
The captured news input and sentiment output evaluated for a candidate signal during a
run.
_Avoid_: News signal, recommendation

**Alert**:
A message that was sent to the user and is linked to its candidate signal and news
analysis.
_Avoid_: Trade, order

**Error Record**:
A captured failure associated with a run and its processing stage.
_Avoid_: Exception log
