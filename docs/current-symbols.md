# Current Symbols Cache

`data/private/current-symbols.json` is an ignored post-market cache generated
from fresh Robinhood broker payloads. It exists for planning and fast universe
exclusion, not for market-hours trading authority.

Robinhood remains the source of truth. Refresh Robinhood before placing,
reviewing, or cancelling real orders.

## Files

- `data/private/current-symbols.json`: compact machine-readable broker snapshot.
- `data/private/close-summary.md`: human-readable post-market summary.
- `data/private/top-10-buy-candidates.md`: previous-run downside shortlist.
- `data/private/top-10-sell-candidates.md`: previous-run upside shortlist.
- `data/private/sold-today.md`: durable pending-reopen queue; not ownership
  state or sell history.
- `data/private/order-ledger.csv`: append-only audit history, not ownership
  state.
- `data/private/LIVE_STATE.md`: deprecated legacy snapshot; do not use it as
  the handoff surface.

## What It Solves

When the user says "open 50", the fast selection rule is:

1. Fetch live Robinhood positions and active equity orders.
2. Build the blocked-open symbol set from owned symbols plus symbols with active
   orders.
3. Read `data/universe.csv`.
4. Apply `data/symbol-policy.csv`.
5. Pick eligible active/tradable universe symbols not in the blocked set.

During market hours, do that directly from live Robinhood responses. After
extended-hours trading closes, the 5 PM daily automation writes
`current-symbols.json` so agents can inspect the last broker-backed state
quickly.

## Command

After saving fresh broker payloads under `data/private/latest/`, run:

```bash
PYTHONPATH=src python -m agentic_strategy.current_symbols \
  --account-key Agentic \
  --portfolio-json data/private/latest/portfolio.json \
  --positions-json data/private/latest/positions.json \
  --orders-json data/private/latest/orders.json \
  --output-json data/private/current-symbols.json \
  --summary-md data/private/close-summary.md \
  --universe data/universe.csv \
  --symbol-policy data/symbol-policy.csv \
  --open-limit 50
```

The command prints an `open_candidates=` line when `--open-limit` is greater
than zero.

## Cache Contents

The JSON stores:

- portfolio cash, buying power, and account value
- owned symbols from non-zero Robinhood positions
- active buy-order symbols
- active sell-order symbols
- blocked-open symbols
- active order details
- optional open candidates from `data/universe.csv` after symbol policy

Do not commit this file. It can include order ids, quantities, balances, and
position details.

Use `docs/shortlists.md` for the top-10 buy/sell candidate files that speed up
the next run's first quote pass.
