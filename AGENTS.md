# Agent Instructions

Read this file before changing strategy logic, docs, data, or automation code.

## Mission

Build a disciplined execution system for the user's broad fractional-stock
averaging strategy. The system should reduce manual scanning, preserve the
original rules, and make rule violations visible before money is put at risk.

## Non-Negotiable Rules

- Sell monitoring has priority over buying. A 10% profit window can be brief.
- Double-down obligations have priority over opening or reopening positions.
- Maintain a 10% cash buffer.
- Keep each single position under 10% of total portfolio value.
- Do not apply a share-price cap to new openings; available deployable cash is
  the opening constraint.
- Do not treat unsettled cash as spendable in a cash account.
- Do not add wash-sale cooldowns or tax-aware trading blocks; strategy decisions
  use actual fill prices and actual dollars invested.
- Do not place real orders unless the active broker tool workflow allows it and
  the user has given any required explicit confirmation.
- When emergency cash is needed, rank green positions below the 10% target by
  highest positive return first.
- Record why every skipped action was skipped.

## Current Broker Tooling Assumptions

The current Robinhood agent tools can inspect accounts, portfolio, positions,
quotes, tradability, and equity orders. They can review and place equity orders,
but real order placement requires the review and confirmation workflow described
by the tool at runtime.

Do not assume the tool can enumerate every Robinhood-tradable symbol. A universe
source must be supplied or built, then each candidate must be checked for
tradability and fractional eligibility before trading.

## Current Implementation

The local Python monitor is read-only. It evaluates snapshots and emits decision
reports. It does not connect to Robinhood and it does not place orders.

Run it with:

```bash
PYTHONPATH=src python3 -m agentic_strategy.monitor \
  --portfolio examples/portfolio.json \
  --positions examples/positions.csv \
  --quotes examples/quotes.csv \
  --universe examples/universe.csv \
  --config-json config/strategy.example.json
```

Run tests with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Priority Loop

During regular market hours, run the decision loop in this order:

1. Reconcile account, positions, orders, and fills.
2. Quote owned positions.
3. Identify full-position sells at or above 10% combined return.
4. Identify due double-downs.
5. If double-down cash is short, identify green positions to liquidate.
6. Only if no double-down is due and the cash buffer is safe, open or reopen
   positions from the eligible universe.
7. Log all candidates, actions, blocks, and stale data.

## Implementation Standard

Prefer boring, auditable code. Strategy state should be reconstructable from
broker data plus the local ledger. If broker data and local data disagree, stop
new buying and reconcile before continuing.
