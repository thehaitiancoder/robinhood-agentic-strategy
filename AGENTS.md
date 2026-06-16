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

If Robinhood or the exchange shows a symbol is halted, paused, frozen, or not
currently accepting orders, treat that symbol as temporarily broker-blocked.
Do not place market buy, sell, reopen, or double-down orders while it is
halted. Do not use the frozen displayed price as normal quote authority. If
the halted symbol would otherwise be a qualifying sell or double-down, report
the action as blocked by the halt and email the user with the appropriate
blocked sell/DD subject. If it is not an executable candidate, skip it with the
halt reason and re-check after trading resumes.

When the user says they canceled a pending order, do not rely on chat or local
state alone. Refresh Robinhood orders first. If the broker shows the order is
canceled, rejected, or otherwise no longer active, remove it from active-order
blocking logic for DD/opening decisions. The 1 PM close automation should
import the cancellation into the audit ledger.

If a market-hours run cannot exhaustively scan the full live position basket,
it must still validate top downside holdings directly before reporting that no
double-down is due. Any owned symbol exposed by the top downside shortlist, a
partial broker/fast scan, or other current broker-backed evidence at `<= -10%`
return with no active buy order is a mandatory DD verification candidate. For
each such symbol, fetch the filled buy/order history needed to reconstruct the
current lot state, calculate every same-symbol DD lot whose trigger is at or
above the current ask, refresh the live quote, and if current ask price is at or
below the deepest included trigger and cash/risk checks pass, review/place one
combined order with `quantity` equal to the sum of those due lot shares. After
placement, inspect the broker returned order price and immediately cancel an
active DD order if that price is missing or above the deepest included trigger.
If Robinhood rejects the fractional DD quantity, retry the integer part only
when it is at least 1 share. Do not stop after checking only recently doubled
down symbols.

If the monitor cannot complete full DD coverage and also cannot verify the
mandatory top-downside candidates because the fast path is blocked, broker
payloads are too large/truncated, permissions are read-only, or required order
history cannot be fetched, the run is blocked. It must not report "no DD due,"
"no order placed," or a routine no-action result. Start the report with
`DD SCAN BLOCKED`, email `rdgustave@gmail.com` with subject
`DOUBLE-DOWN SCAN BLOCKED - Robinhood strategy`, include the exact blocker, and
state which symbols were and were not verified.

Shortlist files under `data/private/top-10-buy-candidates.md` and
`data/private/top-10-sell-candidates.md` are speed hints from the previous run.
At the start of a market-hours check, quote those symbols first because the next
DD or sell is likely to come from that set. They are not trading authority:
refresh Robinhood before acting. Update the shortlist files only after the main
automation work is complete and no executable order is waiting.

`data/private/sold-today.md` is the ignored daily queue of symbols sold during
the current Pacific trading day that have not yet been reopened. It is not a
sell history and not an ownership source. Reset it at the beginning of each
market day. During sell execution, do not write it while an executable sell or
double-down is waiting. After the sell workflow is done and sold orders are
confirmed filled, append only the sell time and symbol, one line per pending
reopen. After a reopen buy is confirmed filled, remove that symbol from the
file. See `docs/sold-today.md`.

## User Shortcuts

The user may use short commands. Treat them as exact workflow requests:

- `STRAT CHECK`: run the full priority loop.
- `SELL CHECK`: find 10% sell targets first.
- `SELL AUTO UNTIL CLOSE` or `SAUCE`: manual chat trigger for a sell-only loop
  through 12:59 PM Pacific. This is pre-authorized to place qualifying
  full-position market sells without another user confirmation after a clean
  broker review. Process one candidate at a time: scan, refresh/review the
  candidate, sell immediately if bid-side return is still at least 10% and the
  broker shows no halt/restriction/block, then resume scanning until 12:59 PT.
  It authorizes sells only; it does not authorize DDs, openings, or reopens.
- `DD CHECK`: find due double-downs.
- `CASH CHECK`: check deployable cash after all higher-priority obligations.
- `SYNC STATE`: refresh Robinhood and update post-market cache/audit files.
- `ORDER CHECK`: check queued/open/recent equity orders.
- `FILL CHECK`: import order history and fills.
- `OPEN CASH`: find eligible new openings after higher-priority checks pass.
- `SELL REVIEW`: review sell-ready full-position market sells.
- `DD REVIEW`: review due double-down market buys.
- `REOPEN SOLD`: read today's pending-reopen list, refresh Robinhood, and
  reopen eligible sold names only after sell/DD obligations and cash buffer
  checks.
- `SOLD TODAY`: show or update the daily sold-not-reopened queue.
- `FAST QUOTES`: use `scripts/rh_fast.mjs quotes` for read-only bulk quotes.
- `FAST ORDERS`: use `scripts/rh_fast.mjs orders` for read-only order scans.
- `FAST POSITIONS`: use `scripts/rh_fast.mjs positions` for read-only
  position scans, optionally with bulk quotes.
- `FAST OPEN PLAN`: use `scripts/rh_fast.mjs open-plan` to compare
  `data/universe.csv` against live Robinhood positions and active orders.
- `FAST WATCH`: use `scripts/rh_fast.mjs watch` for rough sell/DD watch
  candidates, then confirm through the normal broker review/place workflow.
- `FAST UNIVERSE`: use `scripts/bulk_validate_robinhood_universe.mjs` for
  read-only universe validation after explicit bulk-validation approval.

See `docs/shortcuts.md` for the committed shortcut reference.

## Automation Monitor

The recurring Codex automations are:

- Market-hours half-hour slot automations: weekday entry-point checks at
  06:00, 06:30, 07:00, 07:30, 08:00, 08:30, 09:00, 09:30, 10:00, 10:30,
  11:00, 11:30, 12:00, and 12:30 Pacific. Their ids follow
  `HH-MM-pt-rh-mkt`; their visible names start with `HH:mm PT - RH MKT`.
  Each half-hour run must perform the main priority loop first, then if no
  executable sell/DD remains and the +15 minute mark is still ahead, stay in
  the same thread and run a fast +15 minute sell/DD recheck. This gives
  practical 15-minute coverage through the scheduler lane that has proven to
  fire.
- `robinhood-strategy-1-pm-close-check`: weekday exact 1:00 PM Pacific
  post-market reconciliation and summary.
- After-hours trade automations: weekday checks at 2:00 PM, 3:00 PM, and
  4:00 PM Pacific. Their ids are `14-00-pt-rh-ah`, `15-00-pt-rh-ah`, and
  `16-00-pt-rh-ah`; their visible names start with `HH:mm PT - RH AH`.
  These slots use after-hours bid/ask prices only for execution decisions and
  are pre-authorized only for whole-share after-hours limit orders plus regular
  market queued fractional sell leftovers after a confirmed whole-share sell.
- `17-00-pt-rh-daily-summary`: daily exact 5:00 PM Pacific read-only strategy
  performance summary. It must not place, review, prepare, cancel, or suggest
  orders.
- `weekly-rh-symbol-policy-refresh`: Sunday 8:00 AM Pacific read-only policy
  refresh. It updates generated rows in `data/symbol-policy.csv` from
  six-month historical intraday range data. It uses Yahoo Finance first and
  falls back to Robinhood historical bars for any symbol where Yahoo fetching
  fails. It must not place, review, prepare, or suggest orders.
- `monthly-rh-universe-discovery`: first Saturday of each month at 8:00 AM
  Pacific read-only universe discovery. It fetches current Nasdaq Trader symbol
  directories, validates new common-stock candidates through Robinhood
  tradability, merges only active/tradable/fractional symbols into
  `data/universe.csv`, preserves rejected evidence under `data/runtime/`, and
  refreshes generated symbol policy rows. It must not place, review, prepare,
  cancel, or suggest orders.

The legacy combined `robinhood-strategy-market-monitor` automation is paused
because it created repeated threads named `RH MKT 30m` and dynamic thread-title
renaming was not reliably available inside automation runs. Do not reactivate
that combined automation unless the fixed slot automations are removed.

Standalone quarter-hour slot automations such as `10-45-pt-rh-mkt` and
`11-15-pt-rh-mkt` are paused. On 2026-06-10 the app skipped those new
standalone +15 jobs while the older 00/30 jobs fired, so they are not the
reliable coverage path. Do not unpause them unless the scheduler behavior is
retested and proven.

The market-hours half-hour automations and their in-thread +15 rechecks are
pre-authorized to place qualifying
strategy sell and double-down orders directly when the broker tool workflow
allows placement. They email `rdgustave@gmail.com` after urgent sell or
double-down orders are executed or blocked, including blocked DD scans. They do
not place new-opening buys unless the user explicitly authorizes openings in
that run.

The after-hours trade automations are separate from the 1 PM close
reconciliation. They must first check Pacific time and run only during their
scheduled after-hours window, never at or after 5:00 PM Pacific. They may place
qualifying whole-share DD limit buys when the live after-hours ask is at or
below the deepest due trigger. They may place qualifying whole-share profit
sell limit orders when the live after-hours bid gives at least a 10% return.
For a sell with fractional shares remaining, after the whole-share after-hours
sell is confirmed filled, they may queue only the fractional leftover as a
regular-hours market sell. They must not use official close as the execution
price, must not place fractional after-hours orders, must not place new
openings or tracking reopens, and must not reactivate the 1 PM close lane as a
trading job.

The 5 PM daily summary automation is read-only reporting. It may fetch
portfolio, positions with quotes, and all equity order history for the Agentic
account, then write `data/private/daily-summary.md`,
`data/private/daily-summary.json`, and
`data/private/daily-return-cycles.csv`. It must not review, place, cancel,
prepare, or suggest orders.

Post-sell tracking reopen exception: after a qualifying profitable sell order
is confirmed filled during a market-hours automation run, the automation is
pre-authorized to immediately reopen the same symbol as a base tracking lot
without waiting for user confirmation. Do not run a broad DD scan between the
sell fill and this tracking reopen. Only apply the fast blockers already known
or immediately checkable: current buying power and 15% cash buffer, symbol
policy permits reopen, known due or cash-short DDs from this run, active buy
order for the same symbol, halted/restricted broker state, and normal base-lot
sizing. If the tracking reopen is placed and later confirmed filled, remove
that symbol from `data/private/sold-today.md` if present. If policy blocks
reopen, do not add the symbol to `sold-today.md`. If another blocker or the
cash buffer blocks reopen, leave or add the symbol in `sold-today.md` for later
reopening.

Every market-hours automation prompt must start with a hard time gate before
reading docs or calling Robinhood. If a fixed-slot run starts outside its
slot-valid window, or at/after 13:00 Pacific, it must write only a concise
late-start skip if possible and stop without broker queries, order reviews, or
local trading-state writes. This prevents Codex missed-run catch-up from
launching an old morning market check beside the 13:00 close automation.

`robinhood-strategy-1-pm-close-check` must not place buy or sell orders because
the regular market is closed at 1:00 PM Pacific. Its job is to refresh
Robinhood broker truth, import broker order history/fills/cancellations into
the audit ledger, update `data/private/current-symbols.json`, write
`data/private/close-summary.md`, produce a close summary, and email if DD scan
coverage is blocked for next-session review. This 1 PM run is explicitly
authorized to update repo-local private state.

`weekly-rh-symbol-policy-refresh` must run only as an off-market weekend policy
maintenance job. It may run `scripts/weekly_symbol_policy_refresh.mjs` and
`agentic_strategy.validate_symbol_policy`. It may fetch current Agentic owned
symbols read-only for classifying generated policy rows, and it may fetch
historical market data for universe symbols. Yahoo Finance is the primary
historical source; if Yahoo fetching fails for a symbol, use Robinhood
historical bars for that symbol before counting it as failed. It must not call
broker order review/place tools, modify `sold-today.md`, update shortlists,
write the ledger, or touch live trading state.

`monthly-rh-universe-discovery` must run only as an off-market first-Saturday
maintenance job. It may run `scripts/monthly_universe_discovery.mjs`,
`scripts/weekly_symbol_policy_refresh.mjs`, and
`agentic_strategy.validate_symbol_policy`. Its Robinhood usage is limited to
read-only tradability validation for candidate symbols and read-only historical
data needed by the policy refresh. It must not call broker order review/place
tools, modify `sold-today.md`, update shortlists, write the ledger, or touch
live trading state.

The market automation names intentionally put the time at the front because the
saved automation name is the reliable mobile chat-list label. Each market run
should still start its first visible response with `MM-DD HH:mm PT - RH MKT`.
If a Codex `set_thread_title` tool is available in that run, rename the thread
to the same timestamp-first format; if it is unavailable, do not spend trading
time trying to force a rename. Keep each automation `cwds` setting to the repo
root only; adding the automation memory directory as a second `cwd` launches
duplicate threads. See `docs/automation-monitor.md` before changing automation
configuration.

Codex project-local automation permissions live under `.codex/config.toml` and
`.codex/rules/robinhood-automation.rules`. They are committed intentionally so
new PCs and automation runs can load the same repo-local write/network policy.
If a market or close run reports denied writes for repo-local files or the fast
MCP shell path is blocked, read `docs/codex-automation-permissions.md` before
changing automation settings.

## Mission

Build a disciplined execution system for the user's broad fractional-stock
averaging strategy. The system should reduce manual scanning, preserve the
original rules, and make rule violations visible before money is put at risk.

## Non-Negotiable Rules

- Sell monitoring has priority over buying. A 10% profit window can be brief.
- Sell priority must not starve double-downs. After a market-hours run places
  and confirms or blocks the current sell batch, it must proceed to due DD
  verification before starting another broad sell batch or skipping to the +15
  recheck. Remaining sell-watch names are not a valid reason to skip DDs.
- Double-down obligations have priority over opening or reopening positions.
- Maintain a 15% cash buffer for openings and reopens. That buffer is reserved
  for double-down obligations, so a due DD must not be blocked merely because
  executing it would move buying power below the 15% floor.
- Keep each single position under 10% of total portfolio value.
- Do not apply a share-price cap to new openings; available deployable cash is
  the opening constraint.
- Do not treat unsettled cash as spendable in a cash account.
- Do not add wash-sale cooldowns or tax-aware trading blocks; strategy decisions
  use actual fill prices and actual dollars invested.
- Strategy stock orders use immediate market execution; do not design GTC limit
  target exits or a mixed market/limit executor.
- `SELL AUTO UNTIL CLOSE` / `SAUCE` is a manual chat pre-authorization for
  full-position 10% profit sells only. During that trigger, do not stop for
  another user confirmation once broker review is clean; place the qualifying
  sell immediately and keep scanning until 12:59 PM Pacific.
- Opening or reopening stocks at or above `$1.00` uses dollar-based fractional
  sizing. Sub-dollar penny stocks use whole-share quantity sizing and should
  not be bought fractionally.
- Apply `data/symbol-policy.csv` before new openings and reopens. A symbol with
  `allow_open=false` must not be opened as a new position. A symbol with
  `allow_reopen=false` must not be reopened after a sell and should not be
  appended to `sold-today.md` as a pending reopen. Keep filtered symbols in
  `data/universe.csv`; the policy overlay controls strategy eligibility.
- The strategy goal is automatic market execution when criteria are met. Do not
  require manual monitoring as a strategy rule.
- For market-hours automation sell and double-down checks, process one
  executable candidate at a time: refresh the quote, review if the broker tool
  requires it, and place immediately if still qualified and not blocked. The
  1:00 PM Pacific close automation is post-market only and must not place
  orders.
- For after-hours automations, process one executable whole-share candidate at
  a time. DD buys must be after-hours limit buys using the integer part only,
  with the limit at or below both the live after-hours ask and the deepest due
  trigger. Profit sells must be after-hours limit sells for the integer
  sellable quantity, using live after-hours bid as the sell-side execution
  price. If a whole-share sell fills and a fractional remainder is still
  sellable, queue that remainder as a regular-hours market sell. Do not use
  official close as an after-hours execution price.
- After a market-hours profitable sell is confirmed filled, immediately reopen
  that same symbol as a base tracking lot when the fast blockers pass and
  symbol policy permits reopen. Do not delay this tracking reopen for a broad
  DD scan or local persistence. This is the only standing automation exception
  to the rule that reopens need explicit user authorization.
- If a full owned-position scan is incomplete, verify the top downside holdings
  directly before declaring no DD. A current `<= -10%` broker-backed return is
  a mandatory DD verification trigger, not automatic buy authority; reconstruct
  lot state, calculate all same-symbol due lots, and compare current ask to the
  deepest included trigger first.
- If DD coverage remains incomplete after that fallback, report `DD SCAN
  BLOCKED`, email the user, and do not present the run as a successful no-action
  scan.
- Lot 1 is the base buy. Lots 2-5 trigger every 10% drop, lots 6-10 every 20%,
  lots 11-15 every 40%, and lots 16+ every 80%; each new lot doubles the prior
  lot's share count.
- Double-down orders must follow the share ladder, not a rounded dollar amount.
  When multiple DD lots are due for the same symbol at the current ask, combine
  them into one broker order with `quantity` equal to the sum of the due lot
  shares. Use dollar estimates only for cash, concentration, and affordability
  checks. If Robinhood rejects the fractional DD quantity, retry with only the
  integer part of that same quantity when the integer part is at least 1 share;
  otherwise report the DD as broker-blocked.
- A DD is executable only when the fresh broker buy-side ask is at or below the
  deepest included DD trigger. After placing a DD, immediately compare the
  broker returned `price` or `average_price` with that deepest included trigger;
  if an active order is missing a price or is above the trigger, cancel it
  immediately and report the guard action.
- For DD affordability, use actual broker buying power, not disposable cash
  after the 15% floor. The cash floor blocks new openings and reopens, but it is
  explicitly reserved to fund DDs. If due DD cost exceeds actual buying power,
  process affordable DDs first and then enter emergency green cash mode.
- Do not place real orders unless the active broker tool workflow allows it,
  including any runtime review requirement. The market-hours monitor has
  standing user authorization for qualifying sell orders, double-down orders,
  and immediate base tracking reopens after confirmed profitable sell fills, so
  it should not wait for chat confirmation when the broker review is clean. The
  1:00 PM Pacific close automation must not place orders.
- Do not place orders for halted/paused/frozen symbols. A halt is a temporary
  broker/market block; re-quote and re-evaluate only after trading resumes.
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
- `agentic_strategy.symbol_policy`: reads committed strategy filters from
  `data/symbol-policy.csv`. These filters block new opens and reopens without
  changing broker-truth universe fields and without blocking target sells or
  double-down checks unless a future policy explicitly says so.
- `agentic_strategy.shortlists`: writes
  `data/private/top-10-buy-candidates.md` and
  `data/private/top-10-sell-candidates.md` from fresh broker positions and
  quotes. These are previous-run speed hints to check first, then refresh after
  the main work is complete.
- `agentic_strategy.sold_today`: resets, appends, or removes symbols from
  `data/private/sold-today.md`, the daily queue for symbols sold today and not
  yet reopened. Append only after sell execution is done and fills are
  confirmed. Remove only after the reopen buy is confirmed filled.
- `agentic_strategy.live_state`: deprecated legacy Markdown snapshot writer.
  Do not use `data/private/LIVE_STATE.md` as the trading handoff surface.
- `scripts/rh_fast_mcp_client.mjs`: shared read-only Robinhood MCP session
  helper for fast broad scans.
- `scripts/rh_fast.mjs`: read-only fast commands for quotes, orders, positions,
  portfolio, open planning, and sell/DD watch screens. These scripts must not place
  orders.
- `agentic_strategy.daily_summary`: writes the 5 PM read-only performance
  report from fresh broker portfolio, position/quote, and order-history
  payloads.
- `scripts/weekly_symbol_policy_refresh.mjs`: weekend read-only historical
  range refresh for generated `data/symbol-policy.csv` rows. It fetches Yahoo
  historical data first and falls back to Robinhood historical bars when Yahoo
  fails for a symbol. It writes metrics, diffs, backups, and summaries under
  `data/runtime/` and only replaces the committed policy file after safety
  validation passes.
- `scripts/monthly_universe_discovery.mjs`: first-Saturday read-only universe
  discovery. It fetches Nasdaq Trader symbol directories, filters current
  common-stock candidates not already in `data/universe.csv`, validates them
  through Robinhood tradability, writes accepted and rejected evidence under
  `data/runtime/monthly-universe-discovery/`, and merges only
  active/tradable/fractional rows into `data/universe.csv`.
- `scripts/bulk_validate_robinhood_universe.mjs`: read-only universe
  tradability validator built on the shared fast MCP client.

Do not commit private ledger data, current-symbol cache files, close summaries,
shortlist files, `sold-today.md`, legacy live-state snapshots, raw broker
payloads, or full account numbers. For cross-computer work, clone/pull the
committed repo and refresh live broker state from Robinhood on that machine.
Only run local persistence commands when the user asks for them, during the
1 PM close automation, after confirmed sells or confirmed reopens for the daily
sold-today queue, or for end-of-run shortlist cleanup.

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
2. Reset `data/private/sold-today.md` if this is the first run of the Pacific
   trading day.
3. Read the previous-run top-10 buy/sell shortlist files if present, then quote
   those symbols first.
4. Quote the remaining owned positions in batches. `FAST WATCH` may be used as
   a read-only speed screen, but any candidate still needs normal
   single-symbol confirmation before execution.
5. Identify full-position sells at or above 10% combined return.
   After a profitable sell is confirmed filled, immediately attempt the
   pre-authorized base tracking reopen for that same symbol when the fast
   blockers pass and symbol policy permits reopen. Do this before any broad DD
   scan, and do not delay it for local persistence.
6. Identify due double-downs. If the full basket scan is incomplete, directly
   verify the top downside holdings and any currently exposed `<= -10%` owned
   position with no active buy order before declaring that no DD is due.
7. If double-down cash is short against actual broker buying power, identify
   green positions to liquidate.
8. Only if no double-down is due and the cash buffer is safe, open or reopen
   positions from the eligible universe after applying `data/symbol-policy.csv`.
9. Report all candidates, actions, blocks, and stale data.
10. After sell execution is complete and sold orders are confirmed filled,
    append only symbols that still need reopen and are allowed to reopen by
    policy to `data/private/sold-today.md`; after confirmed reopen fills,
    remove those symbols from the file.
11. After all executable work is done, update the top-10 buy and sell shortlist
    files from the just-seen positions and quotes. Write other local audit or
    cache data only when the user explicitly requested persistence in that run.

Do not interpret step 5 as an endless sell loop. Once the current sell batch has
been placed and either filled, blocked, canceled, rejected, or left as a known
active broker order, continue to step 6 using fresh buying power. A DD may be
blocked by insufficient actual buying power, broker/tool restrictions, a halt,
same-symbol active buy/order conflict, missing lot-history proof, concentration
risk, or the market close, but not merely because a refreshed watch still shows
more possible sell candidates.

## Implementation Standard

Prefer boring, auditable code. Live strategy state should be reconstructable
from Robinhood broker data. The local ledger is optional audit support, not the
source of truth. `current-symbols.json` is a post-market cache, not a trading
authority. If broker data and local data disagree, use broker data for market
decisions, stop new buying if needed, and reconcile local state only when the
user asks for persistence or during the 1 PM close automation.
