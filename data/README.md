# Data Directory

Do not commit private account exports, current-symbol caches, close summaries,
legacy live-state snapshots, raw broker payloads, order ledgers, or logs
containing full account numbers. For cross-computer work, pull the committed
repo and refresh live broker state from Robinhood before trading.

Expected local files:

- `universe.csv`: canonical Robinhood-validated symbols and metadata.
- `private/current-symbols.json`: ignored post-market broker-derived symbol
  cache for planning and universe exclusion.
- `private/close-summary.md`: ignored post-market close summary.
- `private/top-10-buy-candidates.md`: ignored previous-run DD/buy watchlist.
- `private/top-10-sell-candidates.md`: ignored previous-run sell watchlist.
- `private/sold-today.md`: ignored daily sold-not-reopened queue.
- `private/order-ledger.csv`: ignored append-only audit ledger. It is not the
  market-hours ownership source.
- `private/LIVE_STATE.md`: deprecated ignored legacy Markdown snapshot.
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

See `docs/current-symbols.md` for the current post-market cache workflow,
`docs/shortlists.md` for previous-run candidate shortcuts,
`docs/sold-today.md` for the daily sold-not-reopened queue, and
`docs/order-ledger.md` for the local audit ledger workflow.
