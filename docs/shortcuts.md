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

## Fast MCP Rule

`FAST *` shortcuts use `scripts/rh_fast.mjs` or
`scripts/bulk_validate_robinhood_universe.mjs`. They are read-only speed tools
that keep one Robinhood MCP session open for broad scans. They may write ignored
runtime files under `data/runtime/`, but they must not place orders. If a sell
or double-down candidate is found, stop scanning and execute through the normal
single-candidate broker review/place workflow.
