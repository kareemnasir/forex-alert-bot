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

**Candidate Metadata**:
Immutable setup facts attached to a Candidate Signal so later processing can identify
its source and compare it for cooldown or deduplication.
_Avoid_: Cooldown decision, alert history

**Alert Decision**:
A deterministic assessment for one pair and timeframe, including a direction when one
side wins and an explicit alert level that may be No Alert.
_Avoid_: Alert, trade recommendation

**Alert Level**:
The outcome band assigned to an Alert Decision: Strong Watch, Watch, Weak Watch, or
No Alert.
_Avoid_: Signal direction, confidence label

**Invalidation Level**:
The market price beyond which a candidate signal's setup no longer holds. It is context
for a manual decision, not an order placed with a broker.
_Avoid_: Stop-loss order, trade exit

**News Analysis**:
The captured news input and sentiment output evaluated for a candidate signal during a
run.
_Avoid_: News signal, recommendation

**Score Adjustment**:
An inspectable deterministic change to an existing Alert Decision based on News
Analysis; it cannot create a pair, direction, or Candidate Signal.
_Avoid_: News signal, LLM decision

**Alert**:
A message that was sent to the user and is linked to its candidate signal and news
analysis.
_Avoid_: Trade, order

**Error Record**:
A captured failure associated with a run and its processing stage.
_Avoid_: Exception log
