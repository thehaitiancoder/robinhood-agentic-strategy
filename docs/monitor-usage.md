# Read-Only Monitor Usage

The first implementation is a local rule engine. It does not connect to
Robinhood and it never places orders. It evaluates snapshots and prints a JSON
decision report.

## Run the Example

```bash
PYTHONPATH=src python3 -m agentic_strategy.monitor \
  --portfolio examples/portfolio.json \
  --positions examples/positions.csv \
  --quotes examples/quotes.csv \
  --universe examples/universe.csv \
  --config-json config/strategy.example.json
```

## Run Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Inputs

For live account checks, use
[`docs/live-snapshot-workflow.md`](live-snapshot-workflow.md) to convert saved
Robinhood tool payloads into these files under ignored `data/runtime/`.

`portfolio.json`:

```json
{
  "total_value": "1000.00",
  "buying_power": "999.00",
  "cash": "1000.00"
}
```

`positions.csv` requires:

```csv
symbol,quantity,invested_cost,current_lot_index,next_trigger_price,next_lot_shares
```

`quotes.csv` requires:

```csv
symbol,bid_price,ask_price,last_price,updated_at
```

`universe.csv` requires:

```csv
symbol,name,asset_type,tradable,fractional_eligible,active,source,updated_at
```

## Decision Actions

- `sell_target`: full-position sell candidate at or above 10% combined return.
- `double_down_ready`: price reached the next ladder trigger and cash is
  available.
- `cash_short_double_down`: a double-down is due but disposable cash is short.
- `block_double_down`: a hard rule blocks the double-down.
- `emergency_green_sell_candidate`: green position below 10% that can be sold
  to fund higher-priority double-downs.
- `pause_new_positions`: new opens are paused because at least one double-down
  is due.
- `new_open_candidate`: eligible unowned symbol when no double-downs are due.
- `block_new_open`: a hard rule blocks additional openings.
- `block`: missing data or other non-order-specific rule block.

`double_down_ready` metrics include:

- `order_sizing`: `exact_share_quantity`
- `order_quantity`: the exact broker `quantity` to review/place
- `order_amount_source`: `estimate_only_do_not_place_dd_by_dollar_amount`
- `estimated_cost`: cash/risk estimate only, not the DD order input
