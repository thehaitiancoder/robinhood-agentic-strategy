# Agent Shortcuts

Use these short commands when asking any future agent to run the strategy.

| Shortcut | Meaning |
| --- | --- |
| `STRAT CHECK` | Run the full priority loop: sync, sells, double-downs, cash, openings. |
| `SELL CHECK` | Check top sell shortlist first, then refresh full positions/quotes for 10% sell targets. |
| `SELL AUTO UNTIL CLOSE` / `SAUCE` | Manual chat trigger: run a sell-only loop until 12:59 PM Pacific and place qualifying 10% full-position sells immediately after clean broker review. |
| `DD CHECK` | Check top buy/DD shortlist first, then refresh full positions/quotes for due double-downs. |
| `CASH CHECK` | Check deployable cash after buffer, queued orders, and obligations. |
| `SYNC STATE` | Refresh Robinhood and update post-market cache/audit files. |
| `ORDER CHECK` | Check queued/open/recent equity orders from Robinhood. |
| `FILL CHECK` | Import order history and fills into the local ledger. |
| `OPEN CASH` | Find eligible new openings after all higher-priority checks pass. |
| `SELL REVIEW` | Review full-position sells for sell-ready symbols. |
| `DD REVIEW` | Review due double-down orders using combined same-symbol due-lot share quantity. |
| `SOLD TODAY` | Show or update `data/private/sold-today.md`, the durable pending-reopen queue. |
| `REOPEN SOLD` | Reopen eligible names from the pending-reopen queue after live sell/DD/cash checks. |
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
positions and active orders. The 5 PM daily automation writes
`data/private/current-symbols.json` for planning, but it is still a
point-in-time cache.

For `SELL CHECK` and `DD CHECK`, read
`data/private/top-10-sell-candidates.md` and
`data/private/top-10-buy-candidates.md` first if they exist. Quote those
symbols first, then continue the full broker scan if no candidate qualifies.

`SELL AUTO UNTIL CLOSE`, also known as `SAUCE`, is different from `SELL CHECK`.
It is a manual chat trigger with standing user authorization to sell. When the
user invokes it during regular market hours, scan for 10% full-position sell
targets, refresh/review one candidate through the broker workflow, and if the
review is clean and bid-side return is still at least 10%, place the market
sell immediately without asking for another confirmation. Then resume scanning
for the next sell target until 12:59 PM Pacific. This trigger authorizes sells
only; it does not authorize double-downs, openings, reopens, or post-close
orders. Do not delay a qualifying sell for local file writes.

For every qualifying DD, review/place a broker share-quantity order. If multiple
DD lots are due for the same symbol at the current ask, combine those due lot
shares into one order. Do not convert DDs into rounded `dollar_amount` orders.
If Robinhood rejects a fractional DD quantity, retry the integer part only when
it is at least 1 share.

If a DD/full-position scan cannot exhaustively cover the live basket, directly
verify the top downside holdings before saying no DD is due. Any broker-backed
owned position shown at `<= -10%` return with no active buy order is a
mandatory DD verification candidate. Reconstruct lot state from filled buys,
refresh the quote, calculate all same-symbol due lots, then place the combined
due-lot quantity only if current ask is at or below the deepest included trigger
and all cash/risk checks pass.

If that verification cannot be completed, the shortcut result is
`DD SCAN BLOCKED`, not "no DD due." Include the exact blocker and which symbols
were not verified. For automation runs, this must email the user.

## Sold-Today Rule

`data/private/sold-today.md` is an ignored durable pending-reopen queue. The
name is legacy; do not clear it at the beginning of a Pacific trading day.
After confirmed sell fills, append one row per symbol that has not yet been
reopened, including the sold date/time and any known blocked-reopen reason.
After confirmed reopen buy fills, remove those symbols from the file. Do this
after execution is complete, not while another executable sell or double-down
is waiting.

`REOPEN SOLD` reads that list, refreshes Robinhood, skips symbols already held
or covered by active buy orders, then reopens eligible symbols only if there
are no due double-downs, symbol policy permits reopen, and the 15% cash buffer
remains safe. Broker state is still the source of truth.

## Fast MCP Rule

`FAST *` shortcuts use `scripts/rh_fast.mjs` or
`scripts/bulk_validate_robinhood_universe.mjs`. They are read-only speed tools
that keep one Robinhood MCP session open for broad scans. They may write ignored
runtime files under `data/runtime/`, but they must not place orders. If a sell
or double-down candidate is found, stop scanning and execute through the normal
single-candidate broker review/place workflow.
