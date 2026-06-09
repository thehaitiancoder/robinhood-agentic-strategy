# Agent Shortcuts

Use these short commands when asking any future agent to run the strategy.

| Shortcut | Meaning |
| --- | --- |
| `STRAT CHECK` | Run the full priority loop: sync, sells, double-downs, cash, openings. |
| `SELL CHECK` | Refresh positions and quotes, then find 10% sell targets first. |
| `DD CHECK` | Refresh positions and quotes, then find due double-downs. |
| `CASH CHECK` | Check deployable cash after buffer, queued orders, and obligations. |
| `SYNC STATE` | Refresh Robinhood and update post-market cache/audit files. |
| `ORDER CHECK` | Check queued/open/recent equity orders from Robinhood. |
| `FILL CHECK` | Import order history and fills into the local ledger. |
| `OPEN CASH` | Find eligible new openings after all higher-priority checks pass. |
| `SELL REVIEW` | Review full-position sells for sell-ready symbols. |
| `DD REVIEW` | Review due double-down orders. |

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
