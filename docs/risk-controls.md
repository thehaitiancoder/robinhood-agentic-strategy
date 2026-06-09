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
- Symbol is halted, delisted, inactive, not tradable, or not eligible for the
  intended order.
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
- The strategy ledger differs from broker-reported quantity.

## Circuit Breakers

Pause new buying if:

- More than a configured number of orders fail in a short period.
- Broker account state cannot be reconciled.
- Buying power drops unexpectedly.
- Quote data becomes unavailable for owned positions.
- The ledger has missing lot history for an open position.

Pause all automation and ask for review if:

- A real order appears in broker history that the strategy did not create or
  import.
- A sell-ready position cannot be sold due to broker restrictions.
- A required double-down is blocked by the 10% concentration cap.
- The account type changes from cash to margin or vice versa.

## Audit Requirements

For every proposed order, store:

- Rule inputs.
- Quote snapshot.
- Portfolio value and buying power.
- Cash floor and disposable cash.
- Position concentration before and after.
- Broker review result.
- User confirmation state when required.
- Final order result.

