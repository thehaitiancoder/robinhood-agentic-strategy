# Agent Shortcuts

Use these short commands when asking any future agent to run the strategy.

| Shortcut | Meaning |
| --- | --- |
| `STRAT CHECK` | Run the full priority loop: sync, sells, double-downs, cash, openings. |
| `SELL CHECK` | Check top sell shortlist first, then refresh full positions/quotes for 10% sell targets. |
| `DD CHECK` | Check top buy/DD shortlist first, then refresh full positions/quotes for due double-downs. |
| `CASH CHECK` | Check deployable cash after buffer, queued orders, and obligations. |
| `SYNC STATE` | Refresh Robinhood and update post-market cache/audit files. |
| `ORDER CHECK` | Check queued/open/recent equity orders from Robinhood. |
| `FILL CHECK` | Import order history and fills into the local ledger. |
| `OPEN CASH` | Find eligible new openings after all higher-priority checks pass. |
| `SELL REVIEW` | Review full-position sells for sell-ready symbols. |
| `DD REVIEW` | Review due double-down orders using exact `next_lot_shares` quantity. |
| `SOLD TODAY` | Show or update `data/private/sold-today.md`, the daily sold-not-reopened queue. |
| `REOPEN SOLD` | Reopen eligible names from today's pending-reopen list after live sell/DD/cash checks. |
| `FAST QUOTES` | Use the fast read-only MCP script to quote many symbols in one session. |
| `FAST ORDERS` | Use the fast read-only MCP script to fetch active equity orders, or newest orders with `--all`. |
| `FAST POSITIONS` | Use the fast read-only MCP script to fetch positions, optionally with quotes. |
| `FAST OPEN PLAN` | Use the fast read-only MCP script to select eligible openings from live positions/orders plus `data/universe.csv`. |
| `FAST WATCH` | Use the fast read-only MCP script to find rough sell/DD watch candidates; confirm before any order. |
| `FAST UNIVERSE` | Use the fast read-only MCP universe validator after explicit bulk-validation approval. |

## Cross-Computer Rule

Committed files provide the rules, tooling, and shortcuts. Live broker state is
refreshed from Robinhood on each computer.

During market hours, refresh Robinhood before any trading decision. Do not use
`data/private/order-ledger.csv`, `data/private/current-symbols.json`, or legacy
`data/private/LIVE_STATE.md` as the source of truth for current ownership.

For "open N" requests, compare `data/universe.csv` against live Robinhood
positions and active orders. The 1 PM close automation writes
`data/private/current-symbols.json` for planning, but it is still a
point-in-time cache.

For `SELL CHECK` and `DD CHECK`, read
`data/private/top-10-sell-candidates.md` and
`data/private/top-10-buy-candidates.md` first if they exist. Quote those
symbols first, then continue the full broker scan if no candidate qualifies.

For every qualifying DD, review/place the broker order with `quantity` equal to
the exact `next_lot_shares` value. Do not convert DDs into rounded
`dollar_amount` orders.

If a DD/full-position scan cannot exhaustively cover the live basket, directly
verify the top downside holdings before saying no DD is due. Any broker-backed
owned position shown at `<= -10%` return with no active buy order is a
mandatory DD verification candidate. Reconstruct lot state from filled buys,
refresh the quote, then place only if current ask is at or below the exact next
trigger and all cash/risk checks pass.

If that verification cannot be completed, the shortcut result is
`DD SCAN BLOCKED`, not "no DD due." Include the exact blocker and which symbols
were not verified. For automation runs, this must email the user.

## Sold-Today Rule

`data/private/sold-today.md` is an ignored daily pending-reopen queue. It is
cleared at the beginning of each Pacific trading day. After confirmed sell
fills, append only the sell time and symbol, one line per symbol that has not
yet been reopened. After confirmed reopen buy fills, remove those symbols from
the file. Do this after execution is complete, not while another executable
sell or double-down is waiting.

`REOPEN SOLD` reads that list, refreshes Robinhood, skips symbols already held
or covered by active buy orders, then reopens eligible symbols only if there
are no due double-downs and the 10% cash buffer remains safe. Broker state is
still the source of truth.

## Fast MCP Rule

`FAST *` shortcuts use `scripts/rh_fast.mjs` or
`scripts/bulk_validate_robinhood_universe.mjs`. They are read-only speed tools
that keep one Robinhood MCP session open for broad scans. They may write ignored
runtime files under `data/runtime/`, but they must not place orders. If a sell
or double-down candidate is found, stop scanning and execute through the normal
single-candidate broker review/place workflow.
