# Live Snapshot Workflow

Use this workflow when an agent has fresh Robinhood tool responses and needs to
run the strategy monitor against them without committing private account data.

## Capture Raw Tool Payloads

Save raw Robinhood tool JSON responses under ignored `data/private/`, grouped by
run timestamp:

```bash
data/private/2026-06-09T093000Z/portfolio.json
data/private/2026-06-09T093000Z/positions.json
data/private/2026-06-09T093000Z/quotes.json
data/private/2026-06-09T093000Z/tradability.json
```

Do not commit these files. Raw payloads can include account-specific balances,
positions, order ids, and other private brokerage state.

## Convert To Monitor Inputs

```bash
PYTHONPATH=src python3 -m agentic_strategy.broker_snapshot \
  --portfolio-json data/private/2026-06-09T093000Z/portfolio.json \
  --positions-json data/private/2026-06-09T093000Z/positions.json \
  --quotes-json data/private/2026-06-09T093000Z/quotes.json \
  --tradability-json data/private/2026-06-09T093000Z/tradability.json \
  --position-state data/private/position-state.csv \
  --output-dir data/runtime/latest \
  --as-of 2026-06-09
```

The converter writes:

- `data/runtime/latest/portfolio.json`
- `data/runtime/latest/positions.csv`
- `data/runtime/latest/quotes.csv`
- `data/runtime/latest/universe.validations.csv`

`--position-state` is optional but needed for reliable offline double-down
evaluation until broker-fill lot reconstruction is implemented. Its columns
are:

```csv
symbol,invested_cost,current_lot_index,next_trigger_price,next_lot_shares
```

## Generate Post-Market Current Symbols

After the close, generate a compact current-symbol cache for planning and fast
universe exclusion:

```bash
PYTHONPATH=src python -m agentic_strategy.current_symbols \
  --account-key Agentic \
  --portfolio-json data/private/latest/portfolio.json \
  --positions-json data/private/latest/positions.json \
  --orders-json data/private/latest/orders.json \
  --output-json data/private/current-symbols.json \
  --summary-md data/private/close-summary.md \
  --universe data/universe.csv \
  --open-limit 50
```

Do not use this cache as market-hours trading truth. Refresh Robinhood before
placing, reviewing, or cancelling orders.

## Refresh The Universe

After tradability is confirmed, merge the validation rows into the canonical
universe:

```bash
PYTHONPATH=src python3 -m agentic_strategy.universe \
  --universe data/universe.csv \
  --validations data/runtime/latest/universe.validations.csv
```

Confirmed symbols stay in `data/universe.csv`. Symbols that later become
inactive, delisted, or non-tradable should be marked inactive or non-tradable
instead of deleted.

## Run The Monitor

```bash
PYTHONPATH=src python3 -m agentic_strategy.monitor \
  --portfolio data/runtime/latest/portfolio.json \
  --positions data/runtime/latest/positions.csv \
  --quotes data/runtime/latest/quotes.csv \
  --universe data/universe.csv \
  --config-json config/strategy.example.json
```

The monitor remains read-only. It emits decisions such as target sells,
double-downs, emergency green sells, and new-open candidates; it does not place
orders.
