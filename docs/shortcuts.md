# Agent Shortcuts

Use these short commands when asking any future agent to run the strategy.

| Shortcut | Meaning |
| --- | --- |
| `STRAT CHECK` | Run the full priority loop: sync, sells, double-downs, cash, openings. |
| `SELL CHECK` | Refresh positions and quotes, then find 10% sell targets first. |
| `DD CHECK` | Refresh positions and quotes, then find due double-downs. |
| `CASH CHECK` | Check deployable cash after buffer, queued orders, and obligations. |
| `SYNC STATE` | Refresh Robinhood, import order history, and regenerate live state. |
| `ORDER CHECK` | Check queued/open/recent equity orders and update the ledger. |
| `FILL CHECK` | Import order history and fills into the local ledger. |
| `OPEN CASH` | Find eligible new openings after all higher-priority checks pass. |
| `SELL REVIEW` | Review full-position sells for sell-ready symbols. |
| `DD REVIEW` | Review due double-down orders. |

## Cross-Computer Rule

Committed files provide the rules, tooling, and shortcuts. Live broker state is
refreshed from Robinhood on each computer.

When `data/private/LIVE_STATE.md` is missing or stale, use `SYNC STATE` before
any trading decision. Do not assume a committed snapshot is current.
