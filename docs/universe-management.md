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

Strategy filters live in `data/symbol-policy.csv`, not in the universe file.
If a stock should remain known but no longer be opened or reopened, add or update
its policy row instead of changing broker-truth fields such as `active`,
`tradable`, or `fractional_eligible`. See `docs/symbol-policy.md`.

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

As of the 2026-06-10 exchange-listed expansion, the universe was expanded from
official Nasdaq Trader symbol directories after explicit user approval for
read-only bulk Robinhood validation. Candidate priority after the S&P indexes
was:

1. Nasdaq Global Select common stocks.
2. Nasdaq Global Market common stocks.
3. Nasdaq Capital Market common stocks.
4. NYSE common stocks.
5. NYSE American common stocks.
6. Other listed common stocks.

Expansion summary:

- 4,280 post-dedupe common-stock candidates parsed from Nasdaq Trader symbol
  directories.
- 1,518 new symbols validated as active/tradable/fractional on Robinhood.
- 222 candidates rejected or not found before the 1,518 target was reached.
- `SEZL` is retained in the universe but marked `tradable=false` and
  `fractional_eligible=false` after Robinhood rejected new fractional openings.
- Committed universe size after the expansion: 3,013 rows, including 3,000
  active/tradable/fractional rows and 13 retained blocked/non-fractional rows.

Ignored expansion artifacts may exist locally under:

- `data/runtime/nasdaqlisted.txt`
- `data/runtime/otherlisted.txt`
- `data/runtime/universe-expansion-candidates.csv`
- `data/runtime/universe-expansion.validations.csv`
- `data/runtime/universe-expansion.rejections.csv`

As of the 2026-06-11 exchange-listed expansion, the remaining Nasdaq Trader
candidate list was filtered against the committed universe and validated again
through Robinhood. This run added another 1,000 active/tradable/fractional
symbols without placing orders.

Expansion summary:

- 2,762 fresh candidates remained after excluding all existing universe rows.
- 1,740 candidates were checked before the 1,000-symbol target was reached.
- 1,000 symbols validated as active/tradable/fractional on Robinhood.
- 733 candidates were rejected or not found during the validation pass.
- Accepted symbols came from the next priority buckets: 618 Nasdaq Capital
  Market common stocks and 382 NYSE common stocks.
- `KALV` is retained in the universe but marked `tradable=false` and
  `fractional_eligible=false` after Robinhood showed a marketwide trading halt
  on 2026-06-11. Revalidate it after trading resumes before re-enabling.
- `CRMT` is retained as active/tradable but marked
  `fractional_eligible=false` after Robinhood rejected a 2026-06-11 sold-list
  reopen with `You cannot open new fractional positions on this stock.`
- Committed universe size after the expansion: 4,013 rows, including 4,000
  rows initially validated as active/tradable/fractional and 15 retained
  blocked/non-fractional rows after the KALV and CRMT blocks.

Ignored expansion artifacts may exist locally under:

- `data/runtime/universe-expansion-2026-06-11-candidates.csv`
- `data/runtime/universe-expansion-2026-06-11.validations.csv`
- `data/runtime/universe-expansion-2026-06-11.rejections.csv`

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

## Bulk Robinhood Validation

`scripts/bulk_validate_robinhood_universe.mjs` performs read-only calls to the
Robinhood Agentic MCP `get_equity_tradability` tool using the locally configured
Codex connector credential. Use it only after the user explicitly approves bulk
Robinhood validation. It uses `scripts/rh_fast_mcp_client.mjs` and does not
place orders.

Default inputs and outputs:

- input: `data/runtime/universe-expansion-candidates.csv`
- output: `data/runtime/universe-expansion.validations.csv`
- rejection evidence: `data/runtime/universe-expansion.rejections.csv`

Run it with the bundled or system Node runtime:

```powershell
$env:RH_ACCOUNT_NUMBER = "<agentic account number>"
node scripts/bulk_validate_robinhood_universe.mjs
```

Useful environment overrides:

```powershell
$env:RH_ACCOUNT_NUMBER = "<agentic account number>"
$env:RH_VALIDATION_NEEDED = "1518"
$env:RH_VALIDATION_DATE = "2026-06-10"
node scripts/bulk_validate_robinhood_universe.mjs
```
