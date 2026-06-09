# Agent Instructions

Read this file before changing strategy logic, docs, data, or automation code.

## Live Broker Source Of Truth

For live trading decisions, Robinhood broker data is the source of truth for
account state, positions, buying power, orders, fills, and queued orders. Local
files under `data/private/` are optional handoff and audit artifacts only; do
not rely on stale local ledger or `LIVE_STATE.md` data to decide whether to buy
or sell.

Do not import broker orders, regenerate `data/private/LIVE_STATE.md`, write the
local ledger, or save private broker payloads unless the user explicitly asks
for persistence in that run. The user may request this with shortcuts such as
`SYNC STATE` or `FILL CHECK`.

When a qualifying sell or double-down candidate exists, execution speed is the
priority. Do not delay a market order for local audit writes or broad reporting.

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

The recurring Codex automations are:

- `robinhood-strategy-market-monitor`: weekday 30-minute checks from 6:00 AM
  through 12:30 PM Pacific.
- `robinhood-strategy-1-pm-close-check`: weekday exact 1:00 PM Pacific close
  check.

They are pre-authorized to place qualifying strategy sell and double-down
orders directly when the broker tool workflow allows placement. They email
`rdgustave@gmail.com` after urgent sell or double-down orders are executed or
blocked. They do not place new-opening buys unless the user explicitly
authorizes openings in that run.

The active automation names are short (`RH MKT 30m` and `RH 1PM close`) because
mobile chat lists truncate long titles. Each run should rename its Codex thread
with a Pacific timestamp-first prefix, for example `MM-DD HH:mm PT - RH MKT`,
so repeated automation chats are distinguishable. Keep each automation `cwds`
setting to the repo root only; adding the automation memory directory as a
second `cwd` launches duplicate threads. See `docs/automation-monitor.md`
before changing automation configuration.

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
- For automation sell and double-down checks, process one executable candidate
  at a time: refresh the quote, review if the broker tool requires it, and
  place immediately if still qualified and not blocked.
- Lot 1 is the base buy. Lots 2-5 trigger every 10% drop, lots 6-10 every 20%,
  lots 11-15 every 40%, and lots 16+ every 80%; each new lot doubles the prior
  lot's share count.
- Do not place real orders unless the active broker tool workflow allows it,
  including any runtime review requirement. The recurring automations have
  standing user authorization for qualifying sell and double-down orders, so do
  not wait for chat confirmation when the broker review is clean.
- When emergency cash is needed, rank green positions below the 10% target by
  highest positive return first.
- When local persistence is explicitly requested, record why every skipped
  action was skipped. Otherwise, do not delay sell or double-down execution for
  local writes.

## Current Broker Tooling Assumptions

The current Robinhood agent tools can inspect accounts, portfolio, positions,
quotes, tradability, and equity orders. They can review and place equity orders.
Treat any broker review or placement workflow as an external tooling constraint;
it does not change the strategy preference for automatic market execution when
criteria are met and the user has authorized that order class.

Do not assume the tool can enumerate every Robinhood-tradable symbol. The
canonical universe is `data/universe.csv`, built from user-supplied candidate
symbols after Robinhood validation. Add confirmed active/tradable symbols to the
list; mark delisted, inactive, or non-tradable symbols inactive instead of
silently deleting them.

## Current Implementation

The local Python monitor is read-only. It evaluates snapshots and emits decision
reports. It does not connect to Robinhood and it does not place orders.

The project also has local ignored live-state tooling for explicit sync/audit
requests:

- `agentic_strategy.ledger`: records broker reviews, placed order snapshots,
  order-history imports, fills, cancellations, rejections, and skipped actions
  under `data/private/order-ledger.csv`.
- `agentic_strategy.live_state`: writes `data/private/LIVE_STATE.md`, the
  central local handoff document for queued orders, positions, account size, and
  ledger status.

Do not commit private ledger data, live-state snapshots, raw broker payloads, or
full account numbers. For cross-computer work, clone/pull the committed repo and
refresh live broker state from Robinhood on that machine. Only run local
persistence commands when the user asks for them.

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
7. Report all candidates, actions, blocks, and stale data. Write local audit
   data only when the user explicitly requested persistence in that run.

## Implementation Standard

Prefer boring, auditable code. Live strategy state should be reconstructable
from Robinhood broker data. The local ledger is optional audit support, not the
source of truth. If broker data and local data disagree, use broker data for
sell and double-down decisions, stop new buying if needed, and reconcile local
state only when the user asks for persistence.
