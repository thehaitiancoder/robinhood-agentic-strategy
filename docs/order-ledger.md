# Local Order Ledger

The order ledger is an ignored, local-only CSV used to keep broker workflow
events reconstructable while the strategy engine remains read-only. It is an
audit log, not the source of current ownership during market hours.

Default path:

```bash
data/private/order-ledger.csv
```

Do not commit this file. It may contain order ids, quantities, account labels,
quote disclosures, and broker timestamps. Use a non-sensitive `--account-key`
such as `Agentic` or a masked last-four label, not a full account number.

## What To Record After Close

Record broker workflow events during explicit audit/persistence runs, especially
the 5 PM daily reconciliation:

- review previews from `review_equity_order`
- placed order snapshots from `place_equity_order`
- order history snapshots from `get_equity_orders`
- fills from order history executions or filled order states
- cancellations and rejections
- skipped actions and the exact skip reason

The ledger is append-only. Imports use broker-derived event keys so rerunning
the same import skips duplicate rows. The importer also skips semantically
duplicate order-state rows when an order was first recorded manually and later
appears in broker order history with the same order id, state, timestamp, fill
quantity, and average price.

After importing current order history during the daily reconciliation workflow, generate
`data/private/current-symbols.json` and `data/private/close-summary.md` with
`agentic_strategy.current_symbols` so a new agent can see the last post-market
broker-backed cache quickly.

The ledger writer uses a local lock file to serialize appends. Even so, agents
should prefer one ledger import or record command per workflow step rather than
many concurrent writes.

## Commands

Record a review preview manually:

```bash
PYTHONPATH=src python3 -m agentic_strategy.ledger \
  record-review \
  --account-key Agentic \
  --symbol CPT \
  --side buy \
  --order-type market \
  --dollar-amount 1.00 \
  --estimated-price 112.97 \
  --time-in-force gfd \
  --market-hours regular_hours \
  --market-data-disclosure "Bid ... Ask ... Last ..."
```

Record a placed order manually:

```bash
PYTHONPATH=src python3 -m agentic_strategy.ledger \
  record-order \
  --account-key Agentic \
  --symbol CPT \
  --side buy \
  --order-type market \
  --order-state queued \
  --order-id 00000000-0000-0000-0000-000000000000 \
  --dollar-amount 1.00 \
  --quantity 0.008850 \
  --cumulative-quantity 0 \
  --estimated-price 112.97 \
  --time-in-force gfd \
  --market-hours regular_hours \
  --placed-agent agentic
```

Import a saved `get_equity_orders` or `place_equity_order` payload:

```bash
PYTHONPATH=src python3 -m agentic_strategy.ledger \
  import-orders \
  --account-key Agentic \
  --orders-json data/private/2026-06-09T093000Z/orders.json
```

Generate the post-market current-symbol cache after broker payloads are saved:

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

Record a skipped action:

```bash
PYTHONPATH=src python3 -m agentic_strategy.ledger \
  record-skip \
  --account-key Agentic \
  --symbol AAPL \
  --reason "existing queued order for symbol"
```

## Ledger Columns

The CSV stores stable columns for event identity, account label, action type,
symbol, order details, broker status, broker timestamps, reason, alerts, quote
disclosure, source, and source payload reference. Empty fields are expected
when a value does not apply to the event.

This is not a durable position ledger and must not be used as the market-hours
owned-symbol list. During market hours, use live Robinhood positions and active
orders. For post-market planning, use the broker-derived cache described in
`docs/current-symbols.md`.
