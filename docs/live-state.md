# Live State Snapshot

`data/private/LIVE_STATE.md` is the first file a future agent should read when
continuing live trading work on a PC that has already refreshed broker state.
It is ignored by git because it can contain private order ids, account labels,
broker timestamps, balances, and position details.

The file summarizes:

- portfolio value, cash, and buying power
- queued equity orders
- open equity positions and sellable quantities
- local ledger row counts
- the required refresh flow

## Refresh Flow

1. Fetch live Robinhood portfolio, equity positions, and equity orders.
2. Save those tool responses under an ignored folder such as
   `data/private/latest/`.
3. Import the order response into the ledger:

```bash
PYTHONPATH=src python3 -m agentic_strategy.ledger \
  import-orders \
  --account-key Agentic \
  --orders-json data/private/latest/orders.json
```

4. Regenerate the live state document:

```bash
PYTHONPATH=src python3 -m agentic_strategy.live_state \
  --account-key Agentic \
  --portfolio-json data/private/latest/portfolio.json \
  --positions-json data/private/latest/positions.json \
  --orders-json data/private/latest/orders.json
```

5. Read `data/private/LIVE_STATE.md` before considering sells, double-downs,
   emergency sells, or new openings.

## Cross-Computer Use

Do not rely on committed live-state snapshots. The committed repo carries the
rules and tooling; Robinhood carries the live account state. On a new computer,
ask the agent for `SYNC STATE` before trading decisions so it refreshes
portfolio, positions, orders, fills, ledger, and `LIVE_STATE.md` locally.

## Recording Requirement

Every real broker workflow event should be recorded in
`data/private/order-ledger.csv`: reviews, placed orders, fills, cancellations,
rejections, and skipped actions. Broker order-history imports are safe to rerun;
the importer skips duplicate order states and fills.
