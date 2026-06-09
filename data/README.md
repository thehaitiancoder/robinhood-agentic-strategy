# Data Directory

Do not commit private account exports, raw broker payloads, or logs containing
full account numbers.

Expected future files:

- `universe.csv`: candidate symbols and metadata.
- `ledger.csv` or `ledger.db`: local strategy state.
- `fills.csv`: normalized fills from Robinhood order history.
- `quotes/`: cached quote snapshots for backtesting and debugging.
- `private/`: ignored local-only files.
- `runtime/`: ignored generated state.

Minimum `universe.csv` columns:

```csv
symbol,name,asset_type,tradable,fractional_eligible,active,source,updated_at
```

