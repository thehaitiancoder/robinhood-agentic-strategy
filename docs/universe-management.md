# Universe Management

The canonical universe is `data/universe.csv`. It is a local, incrementally
built list of symbols that have been checked against Robinhood.

## Source Decision

The strategy does not depend on a third-party list as the final source of truth.
The user can provide symbol batches from any source, but symbols only enter the
canonical universe after a Robinhood tradability check.

When future agents receive symbols:

1. Normalize tickers to uppercase.
2. Check Robinhood tradability in batches.
3. Add confirmed active/tradable symbols to `data/universe.csv`.
4. Mark symbols inactive or non-tradable when Robinhood rejects them, reports
   them inactive, or they appear delisted.
5. Re-check stale records periodically and keep `updated_at` current.

Do not delete delisted or inactive symbols by default. Mark them inactive so the
system has an audit trail and does not keep rediscovering the same dead ticker.

## Current Coverage

As of the 2026-06-09 universe import, `data/universe.csv` contains the original
S&P 500 batch plus S&P MidCap 400 and S&P SmallCap 600 constituents. The
S&P 400/600 batch was pulled from public constituent tables and then validated
against Robinhood instrument data before merging.

Import summary:

- 400 S&P MidCap 400 rows parsed.
- 603 S&P SmallCap 600 rows parsed.
- 1,003 unique source symbols processed.
- 1,002 source symbols validated as active/tradable on Robinhood.
- `CWEN.A` was not found by Robinhood and is kept inactive/non-tradable.
- Committed universe size after the import: 1,495 rows.

Ignored import artifacts may exist locally under
`data/private/sp-400-600.source.csv`,
`data/private/sp-400-600.validations.csv`, and
`data/private/sp-400-600.import-summary.json`. Those files are local evidence
only; the committed durable state is `data/universe.csv`.

## Validation CSV

The merge utility expects the same columns as the canonical universe:

```csv
symbol,name,asset_type,tradable,fractional_eligible,active,source,updated_at
```

Example validation file:

```csv
symbol,name,asset_type,tradable,fractional_eligible,active,source,updated_at
AAPL,Apple Inc.,stock,true,true,true,robinhood_validated,2026-06-09
OLD,,stock,false,false,false,robinhood_validated,2026-06-09
```

Merge it with:

```bash
PYTHONPATH=src python3 -m agentic_strategy.universe \
  --universe data/universe.csv \
  --validations data/private/validated-symbols.csv
```

For review without overwriting:

```bash
PYTHONPATH=src python3 -m agentic_strategy.universe \
  --universe data/universe.csv \
  --validations data/private/validated-symbols.csv \
  --output data/runtime/universe.preview.csv
```
