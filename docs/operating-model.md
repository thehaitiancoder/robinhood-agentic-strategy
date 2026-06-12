# Operating Model

## Market-Hours Priority

The system should spend the most frequent checks on sell monitoring. Opening new
positions and double-downs are important, but sell opportunities at 10% profit
can disappear quickly.

Priority order:

1. Reconcile positions, orders, fills, buying power, and cash.
2. Reset `data/private/sold-today.md` if this is the first Pacific trading-day
   run.
3. Quote all owned positions.
4. Generate full-position sell candidates at or above 10% return.
5. After a confirmed profitable sell fill, immediately attempt the base
   tracking reopen for that same symbol if fast blockers pass.
6. Review due double-downs. The 10% cash floor is DD reserve, not a DD blocker;
   use actual broker buying power for DD affordability.
7. Enter emergency cash mode if double-down cash is short.
8. Open or reopen new positions only if there are no due double-downs, except
   for the immediate post-sell tracking reopen above.
9. Report decisions. Do not write local audit/cache files during market-hours
   execution unless the user explicitly asks, except for updating confirmed
   filled sells and confirmed reopen fills in `data/private/sold-today.md`
   after execution is done.

## Pre-Market

- Pull account and portfolio state.
- Pull open orders and recent fills.
- Read Robinhood broker state directly for the plan.
- Do not rebuild or consult the local audit ledger before market-hours
  execution.
- Reset `data/private/sold-today.md` for the new Pacific trading day.
- Refresh the tradable universe if a source is available.
- Mark symbols that are halted, delisted, non-tradable, or not fractional
  eligible.
- Produce a plan but avoid fractional market orders before regular market hours.

## Regular Session

Run a tight monitor loop over owned positions:

- Read the previous-run top-10 buy and sell shortlist files if present.
- Quote shortlist symbols first.
- Quote owned symbols in batches.
- Calculate sell return using bid-side pricing when available.
- Surface any `sell_ready` positions immediately.
- After a profitable sell is confirmed filled by a market-hours automation,
  immediately reopen the same symbol as a base tracking lot if the fast
  blockers pass: current buying power and 10% cash buffer, known due or
  cash-short DDs from this run, active same-symbol buy order,
  halted/restricted broker state, and normal base-lot sizing. Do not run a
  broad DD scan between the sell fill and this tracking reopen.
- After sell orders from the run are placed and confirmed filled, append only
  sell time and symbol to `data/private/sold-today.md` for symbols still
  waiting for reopen.
- After reopen buys from the run are confirmed filled, remove those symbols
  from `data/private/sold-today.md`.
- Check due double-downs after sell candidates.
- Check new openings last.

The loop should degrade safely if quotes are stale, missing, or inconsistent.
Stale data should block new buys and warn on sell decisions.

## After Close

- Reconcile fills and cancellations.
- Import broker order history into the audit ledger.
- Generate `data/private/current-symbols.json`.
- Generate `data/private/close-summary.md`.
- Generate `data/private/top-10-buy-candidates.md`.
- Generate `data/private/top-10-sell-candidates.md`.
- Reconcile `data/private/sold-today.md` against broker-filled sell orders and
  any completed same-day reopens.
- Treat `data/private/LIVE_STATE.md` as deprecated.
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

Opening and reopening sizing depends on price: stocks at or above `$1.00` use
dollar-based fractional sizing, while sub-dollar stocks use whole-share
quantity sizing. Double-down sizing is share based: every DD order must use the
exact `next_lot_shares` quantity from the ladder so the new lot doubles the
previous lot's filled share count.

Current live tools may require explicit confirmation for real order placement
after review. Future code must obey active tool policy at runtime, but that
confirmation boundary is an external tooling constraint, not a strategy
preference.
