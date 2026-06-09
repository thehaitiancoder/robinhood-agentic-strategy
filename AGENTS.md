# Agent Instructions

Read this file before changing strategy logic, docs, data, or automation code.

## Live Broker Source Of Truth

For live trading decisions, Robinhood broker data is the source of truth for
account state, positions, buying power, orders, fills, and queued orders. Local
files under `data/private/` are optional post-market cache and audit artifacts
only; do not rely on stale local ledger, `current-symbols.json`, close summary,
or `LIVE_STATE.md` data to decide whether to buy or sell.

Do not import broker orders, write the local ledger, regenerate deprecated
`data/private/LIVE_STATE.md`, or save private broker payloads during market
hours unless the user explicitly asks for persistence in that run. The user may
request persistence with shortcuts such as `SYNC STATE` or `FILL CHECK`. The
1:00 PM Pacific close automation is the standing exception for end-of-day
persistence.

When a qualifying sell or double-down candidate exists, execution speed is the
priority. Do not delay a market order for local audit writes or broad reporting.

## User Shortcuts

The user may use short commands. Treat them as exact workflow requests:

- `STRAT CHECK`: run the full priority loop.
- `SELL CHECK`: find 10% sell targets first.
- `DD CHECK`: find due double-downs.
- `CASH CHECK`: check deployable cash after all higher-priority obligations.
- `SYNC STATE`: refresh Robinhood and update post-market cache/audit files.
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
- `robinhood-strategy-1-pm-close-check`: weekday exact 1:00 PM Pacific
  post-market reconciliation and summary.

`robinhood-strategy-market-monitor` is pre-authorized to place qualifying
strategy sell and double-down orders directly when the broker tool workflow
allows placement. It emails `rdgustave@gmail.com` after urgent sell or
double-down orders are executed or blocked. It does not place new-opening buys
unless the user explicitly authorizes openings in that run.

`robinhood-strategy-1-pm-close-check` must not place buy or sell orders because
the regular market is closed at 1:00 PM Pacific. Its job is to refresh
Robinhood broker truth, import broker order history/fills/cancellations into
the audit ledger, update `data/private/current-symbols.json`, write
`data/private/close-summary.md`, and produce a close summary. This 1 PM run is
explicitly authorized to update repo-local private state.

The active automation names are short (`RH MKT 30m` and `RH 1PM close`) because
the saved automation name is a static scheduler label. The run thread title
must be dynamic. Each run's first action should call the Codex
`set_thread_title` tool with a Pacific timestamp-first title, for example
`06-09 09:00 PT - RH MKT`, so repeated automation chats are distinguishable on
mobile. Keep each automation `cwds` setting to the repo root only; adding the
automation memory directory as a second `cwd` launches duplicate threads. See
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
- For market-hours automation sell and double-down checks, process one
  executable candidate at a time: refresh the quote, review if the broker tool
  requires it, and place immediately if still qualified and not blocked. The
  1:00 PM Pacific close automation is post-market only and must not place
  orders.
- Lot 1 is the base buy. Lots 2-5 trigger every 10% drop, lots 6-10 every 20%,
  lots 11-15 every 40%, and lots 16+ every 80%; each new lot doubles the prior
  lot's share count.
- Do not place real orders unless the active broker tool workflow allows it,
  including any runtime review requirement. The market-hours monitor has
  standing user authorization for qualifying sell and double-down orders, so it
  should not wait for chat confirmation when the broker review is clean. The
  1:00 PM Pacific close automation must not place orders.
- When emergency cash is needed, rank green positions below the 10% target by
  highest positive return first.
- When local persistence is explicitly requested, record why every skipped
  action was skipped. The 1:00 PM Pacific close automation is the standing
  daily persistence window. Otherwise, do not delay market-hours sell or
  double-down execution for local writes.

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

The project also has local ignored cache/audit tooling for explicit sync/audit
requests and the 1 PM close automation:

- `agentic_strategy.ledger`: records broker reviews, placed order snapshots,
  order-history imports, fills, cancellations, rejections, and skipped actions
  under `data/private/order-ledger.csv`. This is audit history only, not the
  market-hours ownership source.
- `agentic_strategy.current_symbols`: writes
  `data/private/current-symbols.json` and `data/private/close-summary.md` from
  fresh broker payloads. This gives agents a compact post-market cache and a
  fast universe exclusion set for planning; refresh Robinhood before trading.
- `agentic_strategy.live_state`: deprecated legacy Markdown snapshot writer.
  Do not use `data/private/LIVE_STATE.md` as the trading handoff surface.

Do not commit private ledger data, current-symbol cache files, close summaries,
legacy live-state snapshots, raw broker payloads, or full account numbers. For
cross-computer work, clone/pull the committed repo and refresh live broker
state from Robinhood on that machine. Only run local persistence commands when
the user asks for them or during the 1 PM close automation.

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

1. Reconcile account, positions, orders, and fills from Robinhood.
2. Quote owned positions.
3. Identify full-position sells at or above 10% combined return.
4. Identify due double-downs.
5. If double-down cash is short, identify green positions to liquidate.
6. Only if no double-down is due and the cash buffer is safe, open or reopen
   positions from the eligible universe.
7. Report all candidates, actions, blocks, and stale data. Write local audit or
   cache data only when the user explicitly requested persistence in that run.

## Implementation Standard

Prefer boring, auditable code. Live strategy state should be reconstructable
from Robinhood broker data. The local ledger is optional audit support, not the
source of truth. `current-symbols.json` is a post-market cache, not a trading
authority. If broker data and local data disagree, use broker data for market
decisions, stop new buying if needed, and reconcile local state only when the
user asks for persistence or during the 1 PM close automation.
