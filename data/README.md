# Data Directory

Do not commit private account exports, live-state snapshots, raw broker
payloads, order ledgers, or logs containing full account numbers. For
cross-computer work, pull the committed repo and run `SYNC STATE` to rebuild
local private state from Robinhood.

Expected local files:

- `universe.csv`: canonical Robinhood-validated symbols and metadata.
- `private/LIVE_STATE.md`: ignored first-read live state handoff document.
- `private/order-ledger.csv`: ignored append-only order workflow ledger.
- `ledger.csv` or `ledger.db`: future durable local strategy state.
- `fills.csv`: normalized fills from Robinhood order history.
- `quotes/`: cached quote snapshots for backtesting and debugging.
- `private/`: ignored local-only files.
- `runtime/`: ignored generated state.

Minimum `universe.csv` columns:

```csv
symbol,name,asset_type,tradable,fractional_eligible,active,source,updated_at
```

`source` should be `robinhood_validated` after an agent confirms the symbol
through Robinhood. Mark delisted or rejected symbols as `active=false` and/or
`tradable=false`; do not delete them by default.

See `docs/live-state.md` for the first-read local live-state workflow and
`docs/order-ledger.md` for the current local order/fill/skip ledger workflow.
