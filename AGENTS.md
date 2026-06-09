# Agent Instructions

Read this file before changing strategy logic, docs, data, or automation code.

## First Live-State Check

Before any live broker action, read `data/private/LIVE_STATE.md` if it exists.
That ignored local document is the fastest handoff surface for queued orders,
open positions, account size, buying power, and ledger status. If it is missing
or stale, refresh Robinhood portfolio, positions, and orders, import the order
history into `data/private/order-ledger.csv`, then regenerate
`data/private/LIVE_STATE.md` with `agentic_strategy.live_state`.

Every real broker workflow event must be recorded locally: reviews, placed
orders, fills, cancellations, rejections, and skipped actions.

## User Shortcuts

The user may use short commands. Treat them as exact workflow requests:

- `STRAT CHECK`: run the full priority loop.
- `SELL CHECK`: find 10% sell targets first.
- `DD CHECK`: find due double-downs.
- `CASH CHECK`: check deployable cash after all higher-priority obligations.
- `SYNC STATE`: refresh Robinhood, import order history, and regenerate live state.
- `ORDER CHECK`: check queued/open/recent equity orders.
- `FILL CHECK`: import order history and fills.
- `OPEN CASH`: find eligible new openings after higher-priority checks pass.
- `SELL REVIEW`: review sell-ready full-position market sells.
- `DD REVIEW`: review due double-down market buys.

See `docs/shortcuts.md` for the committed shortcut reference.

## Automation Monitor

The recurring Codex automation is `robinhood-strategy-market-monitor`. It runs
the strategy monitor every 30 minutes on weekdays around market hours, emails
urgent sell-target and double-down alerts to `rdgustave@gmail.com`, and should
write repo-local state plus automation-local memory. See
`docs/automation-monitor.md` before changing automation configuration.

## Mission

Build a disciplined execution system for the user's broad fractional-stock
averaging strategy. The system should reduce manual scanning, preserve the
original rules, and make rule violations visible before money is put at risk.

## Non-Negotiable Rules

- Sell monitoring has priority over buying. A 10% profit window can be brief.
- Double-down obligations have priority over opening or reopening positions.
- Maintain a 10% cash buffer.
- Keep each single position under 10% of total portfolio value.
- Do not apply a share-price cap to new openings; available deployable cash is
  the opening constraint.
- Do not treat unsettled cash as spendable in a cash account.
- Do not add wash-sale cooldowns or tax-aware trading blocks; strategy decisions
  use actual fill prices and actual dollars invested.
- Strategy stock orders use immediate market execution; do not design GTC limit
  target exits or a mixed market/limit executor.
- Stocks at or above `$1.00` use dollar-based fractional sizing. Sub-dollar
  penny stocks use whole-share quantity sizing and should not be bought
  fractionally.
- The strategy goal is automatic market execution when criteria are met. Do not
  require manual monitoring as a strategy rule.
- Lot 1 is the base buy. Lots 2-5 trigger every 10% drop, lots 6-10 every 20%,
  lots 11-15 every 40%, and lots 16+ every 80%; each new lot doubles the prior
  lot's share count.
- Do not place real orders unless the active broker tool workflow allows it,
  including any runtime review or explicit confirmation requirement.
- When emergency cash is needed, rank green positions below the 10% target by
  highest positive return first.
- Record why every skipped action was skipped.

## Current Broker Tooling Assumptions

The current Robinhood agent tools can inspect accounts, portfolio, positions,
quotes, tradability, and equity orders. They can review and place equity orders,
but real order placement requires the review and confirmation workflow described
by the tool at runtime.

Treat that confirmation workflow as an external tooling constraint. It does not
change the strategy preference for automatic market execution when compliant
tooling supports it.

Do not assume the tool can enumerate every Robinhood-tradable symbol. The
canonical universe is `data/universe.csv`, built from user-supplied candidate
symbols after Robinhood validation. Add confirmed active/tradable symbols to the
list; mark delisted, inactive, or non-tradable symbols inactive instead of
silently deleting them.

## Current Implementation

The local Python monitor is read-only. It evaluates snapshots and emits decision
reports. It does not connect to Robinhood and it does not place orders.

The project also has local ignored live-state tooling:

- `agentic_strategy.ledger`: records broker reviews, placed order snapshots,
  order-history imports, fills, cancellations, rejections, and skipped actions
  under `data/private/order-ledger.csv`.
- `agentic_strategy.live_state`: writes `data/private/LIVE_STATE.md`, the
  central local handoff document for queued orders, positions, account size, and
  ledger status.

Do not commit private ledger data, live-state snapshots, raw broker payloads, or
full account numbers. For cross-computer work, clone/pull the committed repo and
run `SYNC STATE` so the agent refreshes live broker state from Robinhood on that
machine.

Run it with:

```bash
PYTHONPATH=src python3 -m agentic_strategy.monitor \
  --portfolio examples/portfolio.json \
  --positions examples/positions.csv \
  --quotes examples/quotes.csv \
  --universe examples/universe.csv \
  --config-json config/strategy.example.json
```

Run tests with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Priority Loop

During regular market hours, run the decision loop in this order:

1. Reconcile account, positions, orders, and fills.
2. Quote owned positions.
3. Identify full-position sells at or above 10% combined return.
4. Identify due double-downs.
5. If double-down cash is short, identify green positions to liquidate.
6. Only if no double-down is due and the cash buffer is safe, open or reopen
   positions from the eligible universe.
7. Log all candidates, actions, blocks, and stale data.

## Implementation Standard

Prefer boring, auditable code. Strategy state should be reconstructable from
broker data plus the local ledger. If broker data and local data disagree, stop
new buying and reconcile before continuing.
