# Operating Model

## Market-Hours Priority

The system should spend the most frequent checks on sell monitoring. Opening new
positions and double-downs are important, but sell opportunities at 10% profit
can disappear quickly.

Priority order:

1. Reconcile positions, orders, fills, buying power, and cash.
2. Quote all owned positions.
3. Generate full-position sell candidates at or above 10% return.
4. Review due double-downs.
5. Enter emergency cash mode if double-down cash is short.
6. Open or reopen new positions only if there are no due double-downs.
7. Persist a decision log.

## Pre-Market

- Pull account and portfolio state.
- Pull open orders and recent fills.
- Rebuild the strategy ledger from broker state plus local history.
- Refresh the tradable universe if a source is available.
- Mark symbols that are halted, delisted, non-tradable, or not fractional
  eligible.
- Produce a plan but avoid fractional market orders before regular market hours.

## Regular Session

Run a tight monitor loop over owned positions:

- Quote owned symbols in batches.
- Calculate sell return using bid-side pricing when available.
- Surface any `sell_ready` positions immediately.
- Check due double-downs after sell candidates.
- Check new openings last.

The loop should degrade safely if quotes are stale, missing, or inconsistent.
Stale data should block new buys and warn on sell decisions.

## After Close

- Reconcile fills and cancellations.
- Update lot counts and next trigger prices.
- Update closed position records.
- Recompute global base coverage.
- Produce a daily report:
  - sold at target
  - sold for emergency cash
  - double-downs placed
  - double-downs blocked
  - new positions opened
  - cash buffer status
  - largest positions as percent of portfolio

## Human Review

The strategy goal is automatic market execution once criteria are met. The user
does not want to manually monitor orders.

Current live tools may require explicit confirmation for real order placement
after review. Future code must obey active tool policy at runtime, but that
confirmation boundary is an external tooling constraint, not a strategy
preference.
