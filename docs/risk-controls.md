# Risk Controls

The goal is not to make the strategy timid. The goal is to keep the system from
failing in the same way manual execution failed: overload, rule drift, and cash
exhaustion.

## Hard Blocks

These conditions must block the proposed action:

- Cash buffer would fall below 10%.
- Single position would exceed 10% of portfolio value.
- Any owned symbol is due for double-down and the proposed action is a new open
  or reopen.
- Symbol is halted, paused for volatility, frozen, delisted, inactive, not
  tradable, or not eligible for the intended order. For temporary halts, do not
  use the frozen displayed price as quote authority; re-quote and re-evaluate
  after trading resumes.
- Quote is stale or missing for a trade decision.
- Cash account sale proceeds are unsettled and therefore not spendable.
- Broker review returns an alert that invalidates the trade.
- Order confirmation is required but not present.

## Soft Warnings

These should warn but not necessarily block:

- Spread is unusually wide.
- Quote source is available but delayed.
- Position is near the 10% concentration cap.
- The symbol had recent corporate action, reverse split, or delisting risk.
- The symbol is thinly traded.
- The post-market cache differs from broker-reported quantity.

## Circuit Breakers

Pause new buying if:

- More than a configured number of orders fail in a short period.
- Broker account state cannot be reconciled from Robinhood.
- Buying power drops unexpectedly.
- Quote data becomes unavailable for owned positions.
- Broker fill history is insufficient to reconstruct lot state for an open
  position.

Pause all automation and ask for review if:

- A real order appears in broker history that the strategy did not create or
  import.
- A sell-ready position cannot be sold due to broker restrictions.
- A sell-ready or DD-ready position is halted. Report the blocked action and
  re-check after trading resumes; do not substitute a different action just
  because the halted symbol cannot trade.
- A required double-down is blocked by the 10% concentration cap.
- The account type changes from cash to margin or vice versa.

## Audit Requirements

During explicit audit/persistence windows, record:

- Rule inputs.
- Quote snapshot.
- Portfolio value and buying power.
- Cash floor and disposable cash.
- Position concentration before and after.
- Broker review result.
- User confirmation state when required.
- Final order result.

