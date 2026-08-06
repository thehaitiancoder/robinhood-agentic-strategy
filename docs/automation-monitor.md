# Codex Automation Monitor

Automation ids:

- Premarket trade slots:
  - `04-00-pt-rh-pre`
  - `05-00-pt-rh-pre`
  - `06-00-pt-rh-pre`
- Market-hours half-hour entry slots:
  - `06-30-pt-rh-mkt`
  - `07-00-pt-rh-mkt`
  - `07-30-pt-rh-mkt`
  - `08-00-pt-rh-mkt`
  - `08-30-pt-rh-mkt`
  - `09-00-pt-rh-mkt`
  - `09-30-pt-rh-mkt`
  - `10-00-pt-rh-mkt`
  - `10-30-pt-rh-mkt`
  - `11-00-pt-rh-mkt`
  - `11-30-pt-rh-mkt`
  - `12-00-pt-rh-mkt`
  - `12-30-pt-rh-mkt`
- Paused standalone quarter-hour slots:
  - `06-15-pt-rh-mkt`
  - `06-45-pt-rh-mkt`
  - `07-15-pt-rh-mkt`
  - `07-45-pt-rh-mkt`
  - `08-15-pt-rh-mkt`
  - `08-45-pt-rh-mkt`
  - `09-15-pt-rh-mkt`
  - `09-45-pt-rh-mkt`
  - `10-15-pt-rh-mkt`
  - `10-45-pt-rh-mkt`
  - `11-15-pt-rh-mkt`
  - `11-45-pt-rh-mkt`
  - `12-15-pt-rh-mkt`
  - `12-45-pt-rh-mkt`
- After-hours trade slots:
  - `13-00-pt-rh-ah`
  - `14-00-pt-rh-ah`
  - `15-00-pt-rh-ah`
  - `16-00-pt-rh-ah`
- `17-00-pt-rh-daily-summary`
- `weekly-rh-symbol-policy-refresh`
- `monthly-rh-universe-discovery`
- `robinhood-strategy-market-monitor` is a paused legacy combined monitor.

Visible automation names:

- Premarket trade slots use `HH:mm PT - RH PRE`, for example
  `04:00 PT - RH PRE`.
- Market-hours entry slots use `HH:mm PT - RH MKT`, for example
  `09:00 PT - RH MKT`.
- After-hours slots use `HH:mm PT - RH AH`, for example
  `13:00 PT - RH AH`.
- `17:00 PT - RH DAILY`
- `Weekly RH Symbol Policy Refresh`
- `Monthly RH Universe Discovery`
- The paused legacy combined monitor is named `RH MKT 30m PAUSED`.

These names are static scheduler labels. They cannot include the current run
date, and dynamic thread-title tools have not been reliably available inside
automation runs. The market monitor uses fixed half-hour entry slots so the
visible mobile chat-list title starts with the entry time even when runtime
thread renaming is unavailable. The +15 minute recheck happens inside the
preceding half-hour thread.

Purpose: run the strategy priority loop during premarket, regular market, and
after-hours windows without the user needing to manually remember checks,
execute qualifying sell and double-down orders quickly, then run a 5:00 PM
Pacific daily reconciliation that updates local state and reports performance.

Schedule:

- Premarket trade automations: weekdays at 4:00 AM, 5:00 AM, and 6:00 AM
  Pacific.
- `04:00 PT - RH PRE` and `05:00 PT - RH PRE` perform their normal
  extended-hours pass first. If no executable whole-share sell/DD remains and
  the `:30` mark for that slot is still in the future, they wait in the same
  thread and run one fast `+30` minute recheck. `06:00 PT - RH PRE` does not
  run a `+30` recheck because it must finish before `06:30 PT - RH MKT`.
- Market-hours entry automations: weekdays every 30 minutes from 6:30 AM
  through 12:30 PM Pacific.
- Each entry automation performs its normal priority loop first. If no
  executable sell/DD remains and the +15 minute mark for that slot is still in
  the future, it waits in the same thread and runs a fast +15 minute sell/DD
  recheck. Example: `10:30 PT - RH MKT` performs the 10:30 check, then covers
  the 10:45 recheck inside the same thread.
- After-hours trade automations: weekdays at 1:00 PM, 2:00 PM, 3:00 PM, and
  4:00 PM Pacific.
- Each after-hours trade automation performs its normal extended-hours pass
  first. If no executable whole-share sell/DD remains and the `:30` mark for
  that slot is still in the future, it waits in the same thread and runs one
  fast `+30` minute recheck.
- `17-00-pt-rh-daily-summary`: every day at exactly 5:00 PM Pacific.
- `weekly-rh-symbol-policy-refresh`: Sundays at 8:00 AM Pacific.
- `monthly-rh-universe-discovery`: first Saturday of each month at exactly
  8:00 AM Pacific.

Observed scheduler limitation: on 2026-06-10 the newly-created standalone
quarter-hour jobs `10-45-pt-rh-mkt` and `11-15-pt-rh-mkt` did not run, while
`11-00-pt-rh-mkt`, `11-30-pt-rh-mkt`, and the older 00/30 jobs did run. The
Codex manual documents custom cron cadence but does not document a minimum
interval. Until retested, use the half-hour entry plus in-thread +15 recheck
design for practical 15-minute market coverage.

Observed scheduler time-base correction: on 2026-06-10, the app treated
automation RRULE `BYHOUR` values as local Pacific wall-clock hours after the
automation prompts were updated. The old UTC-encoded values caused `06:00` to
fire at about `13:00 PT` and `09:00` to fire at about `16:00 PT`. The actual
active automation files must therefore use Pacific-local `BYHOUR` values, not
UTC offsets.

Current intended local encodings are:

- premarket slots:
  - 04:00 PT: `BYHOUR=4;BYMINUTE=0`
  - 05:00 PT: `BYHOUR=5;BYMINUTE=0`
  - 06:00 PT: `BYHOUR=6;BYMINUTE=0`
- market slots:
  - 06:30 PT: `BYHOUR=6;BYMINUTE=30`
  - 07:00 PT: `BYHOUR=7;BYMINUTE=0`
  - 07:30 PT: `BYHOUR=7;BYMINUTE=30`
  - 08:00 PT: `BYHOUR=8;BYMINUTE=0`
  - 08:30 PT: `BYHOUR=8;BYMINUTE=30`
  - 09:00 PT: `BYHOUR=9;BYMINUTE=0`
  - 09:30 PT: `BYHOUR=9;BYMINUTE=30`
  - 10:00 PT: `BYHOUR=10;BYMINUTE=0`
  - 10:30 PT: `BYHOUR=10;BYMINUTE=30`
  - 11:00 PT: `BYHOUR=11;BYMINUTE=0`
  - 11:30 PT: `BYHOUR=11;BYMINUTE=30`
  - 12:00 PT: `BYHOUR=12;BYMINUTE=0`
  - 12:30 PT: `BYHOUR=12;BYMINUTE=30`
- after-hours trade slots:
  - 13:00 PT: `BYHOUR=13;BYMINUTE=0`
  - 14:00 PT: `BYHOUR=14;BYMINUTE=0`
  - 15:00 PT: `BYHOUR=15;BYMINUTE=0`
  - 16:00 PT: `BYHOUR=16;BYMINUTE=0`
- daily summary: `BYHOUR=17;BYMINUTE=0`
- weekly symbol policy refresh: `BYDAY=SU;BYHOUR=8;BYMINUTE=0`
- monthly universe discovery: `BYDAY=1SA;BYHOUR=15;BYMINUTE=0`

The monthly universe discovery automation is saved with `BYHOUR=15` because
the scheduler displays `BYHOUR=8` as `01:00 PT` for that monthly cron. The
prompt still hard-gates on first-Saturday 08:00 Pacific before any broker or
network work.

Every market-hours prompt must still begin with a hard local-Pacific time gate
before reading docs or calling Robinhood. The valid window is the entry slot
through 25 minutes after the slot, never at or after 13:00 PT. Outside that
window, write only a concise late-start skip to automation memory if possible
and stop.

Premarket prompts must also hard-gate before reading docs or calling Robinhood.
The `06:00 PT - RH PRE` automation must stop new broker reviews/placements by
06:25 PT and hard-stop all work before 06:30 PT, leaving a concise handoff if
anything remains, so it cannot overlap the `06:30 PT - RH MKT` automation.

Market holiday gate:

- The committed holiday file is `config/market-holidays.csv`.
- After the hard Pacific-time gate and before docs, Robinhood calls, order
  reviews, or trading/cache writes, premarket, market-hours, after-hours, and
  daily summary automations must run:
  `python -m agentic_strategy.market_calendar --date today --calendar config/market-holidays.csv --market US_EQUITIES`
- If the helper reports `market_status=closed`, the automation writes a concise
  `MARKET HOLIDAY SKIP` note if possible and stops.
- If the helper reports `market_status=early_close`, the automation should
  treat the reported `close_time_pt` as the regular-session boundary for that
  date and avoid normal market-hours work after that boundary.
- Keep the CSV refreshed from NYSE/Nasdaq holiday calendars before the covered
  date range expires.

Thread titles:

- Market-hours automation names must start with the entry slot time, for example
  `09:00 PT - RH MKT`. This is the reliable fallback title in the mobile chat
  list.
- Each market-hours prompt must tell the run not to spend time searching for
  thread-title tools. The first visible response should start with the current
  `MM-DD HH:mm PT - RH MKT` prefix so the run date is still visible after
  opening the thread.
- If the `set_thread_title` tool is available in a future automation run, it
  may rename the thread to `MM-DD HH:mm PT - RH MKT`, but this is best-effort
  only and must not delay sell or double-down execution.
- Premarket automation names start with the slot time, for example
  `04:00 PT - RH PRE`. The first visible response should start with
  `MM-DD HH:mm PT - RH PRE`.
- After-hours automation names start with the slot time, for example
  `13:00 PT - RH AH`. The first visible response should start with
  `MM-DD HH:mm PT - RH AH`.
- The daily summary automation name is `17:00 PT - RH DAILY`; its first visible
  response should start with `MM-DD 17:00 PT - RH DAILY`.
- The monthly universe discovery automation name is
  `Monthly RH Universe Discovery`; its first visible response should start with
  `MM-DD 08:00 PT - RH UNIVERSE`.
- Do not reactivate the paused combined `RH MKT 30m` automation unless the
  fixed time-slot automations are removed; otherwise duplicate runs or
  indistinguishable chat titles can return.
- Do not reactivate paused standalone quarter-hour jobs unless a live scheduler
  retest proves they fire. Otherwise they create false confidence without
  coverage.

Model settings:

- Model: `gpt-5.4`
- Reasoning effort: `xhigh`

Workspace configuration:

- `C:\Users\ralph\.codex\worktrees\de6e\robinhood-agentic-strategy`

The repo has a committed Codex project layer for these runs:

- `.codex/config.toml`
- `.codex/rules/robinhood-automation.rules`
- `docs/codex-automation-permissions.md`

That layer keeps the repo workspace writable, enables network access for the
repo fast MCP scripts, and allows only the narrow command prefixes used for
Robinhood scans and repo-local persistence.

Keep the `cwds` field to this single repo root only. In the Codex automation
tool, `cwds` are runnable workspaces, not generic writable roots. Adding
`C:\Users\ralph\.codex\automations\...` as a second `cwd` causes the same
automation run to create a duplicate thread in the automation directory.

Do not add a second writable automation directory as another `cwd`. If an
automation needs persistent memory outside the repo, configure that as an
automation setting rather than another runnable workspace.

## Market Monitor Execution

The market-hours half-hour entry automations run during regular market hours
and check in this order:

1. sell targets at or above 10% return
2. immediate base tracking reopen after a confirmed profitable sell fill, if
   the fast blockers pass
3. due double-downs
4. emergency green-sell candidates if double-down cash is short
5. deployable idle cash for new openings
6. routine queued orders, open positions, and stale-data status

The user has standing-authorized the market monitor to place qualifying strategy
sell and double-down orders directly, subject to broker tool review and
placement constraints. Speed is priority number one for executable sell and
double-down candidates.

Sell priority is an order-of-operations rule, not permission to starve DDs. Once
the current sell batch has been placed and each attempted sell is filled,
blocked, canceled, rejected, or left as a known active broker order, the run
must move to due DD verification using fresh buying power. A refreshed watch
showing more possible sell candidates is not a valid reason to skip DDs.

DD cash-buffer rule: the 15% cash floor is reserved for double-downs. It blocks
new openings, sold-symbol reopens, and post-sell tracking reopens, but it must
not block a due exact-share DD merely because buying power would fall below the
floor. For DD affordability, use actual broker buying power, concentration, and
broker review checks. If due DD cost exceeds actual buying power, place
affordable DDs first and enter emergency green cash mode for the rest.

Post-sell tracking reopen exception: after a qualifying profitable sell order
is confirmed filled during a market-hours automation run, immediately reopen
that same symbol as a base tracking lot when the fast blockers pass. This
reopen is pre-authorized and must not wait for user confirmation. Do not run a
broad DD scan between the sell fill and this tracking reopen; only check the
fast blockers already known or immediately checkable: current buying power and
15% cash buffer, symbol policy permits reopen, known due or cash-short DDs from
this run, active buy order for the same symbol, halted/restricted broker state,
and normal base-lot sizing. If the reopen is placed and later confirmed filled,
remove the symbol from `data/private/sold-today.md` if present. If policy blocks
reopen, do not add the symbol to `sold-today.md`. If another blocker or the cash
buffer blocks reopen, leave or add the symbol in `sold-today.md` for later
reopening.

Execution rules:

- First action: check current Pacific time before reading docs, querying
  Robinhood, or writing repo state. If the run started outside its slot-valid
  window or at/after 13:00 PT, stop immediately with a late-start skip. Do not
  perform broker scans, order reviews, order placement, sold-today updates,
  shortlist updates, or other market-hour persistence from a late-started
  market slot.
- Do not reset `data/private/sold-today.md` at the start of a new Pacific
  trading day. The helper's legacy `--reset` action only initializes or
  re-renders the durable pending-reopen queue and must preserve existing
  pending entries.
- Read `data/private/top-10-sell-candidates.md` and
  `data/private/top-10-buy-candidates.md` if present, then quote those symbols
  first through Robinhood. Use
  `node scripts/rh_fast.mjs quotes --file data/private/top-10-sell-candidates.md`
  and the matching buy-candidate file when the fast helper is available.
  Review/place any qualifying shortlisted sell or DD immediately before
  starting `FAST WATCH` or another broad owned-position scan. These files are
  speed hints only, so refresh Robinhood before acting.
- Fast read-only scripts from `docs/fast-mcp-workflows.md` may be used to speed
  broad quotes, positions, orders, and watch scans when available.
- Process one executable sell or double-down candidate at a time.
- Do not start a second broad sell batch before checking DDs merely because the
  refreshed watch still has sell-watch names. After the current sell batch is
  resolved or blocked, move to due DD verification. DDs may be skipped only for
  insufficient actual buying power, broker/tool blockers, halted symbols,
  active same-symbol/order conflicts, missing lot-history proof, concentration
  risk, or the market close.
- Refresh the quote immediately before order review.
- If the broker tool requires review, run the review immediately.
- If the review has no blocking alerts and the refreshed price still qualifies,
  place the market order immediately.
- If Robinhood or the exchange shows a symbol is halted, paused, frozen, in a
  volatility pause, or otherwise not currently accepting orders, do not place a
  market order for that symbol. Treat the frozen displayed quote as stale for
  execution. If the symbol would otherwise qualify for a sell or DD, report the
  trade as broker-blocked by the halt in the task transcript and automation
  memory, and re-check after trading resumes. If it is not an executable
  candidate, skip it with the halt reason and continue the priority loop.
- If the user says they canceled a pending order, refresh live Robinhood order
  state before using that symbol in active-order blocking logic. A broker
  state of canceled, rejected, failed, expired, or any other non-active terminal
  state no longer blocks DD/opening decisions. A still-confirmed, queued, new,
  unconfirmed, or partially-filled order remains active and blocks another buy
  for the same symbol.
- For double-downs, review and place share-quantity orders. If one DD lot is
  due, use that lot's exact share count. If multiple DD lots are due for the
  same symbol at the current ask, combine those due lot shares into one broker
  order. Do not place DDs with a rounded `dollar_amount`; dollar values are
  estimates for cash and risk checks only. During regular market hours, this
  exact share quantity remains executable even when `integer_qty=0`, assuming
  Robinhood accepts the fractional buy. If Robinhood rejects the fractional DD
  quantity, retry the integer part only when it is at least 1 share.
- In premarket and after-hours whole-share lanes, a due DD with `integer_qty=0`
  is regular-hours-only and not executable in that lane. It is not missing DD
  coverage and not a DD blocker. `data/runtime/dd-fractional-leftovers.csv` is
  only for decimal remainders left after an integer-share execution or integer
  fallback, not for regular-market exact-share due lots.
- If the full live position basket cannot be exhaustively scanned, the monitor
  must still validate the top downside holdings directly before reporting no
  DD. Any owned symbol shown by the top downside shortlist, a partial broker or
  fast scan, or other current broker-backed evidence at `<= -10%` return and
  with no active buy order is a mandatory DD verification candidate. Fetch the
  filled buy/order history needed to reconstruct current lot state, calculate
  every same-symbol due lot whose trigger is at or above the current ask,
  refresh the live quote, and if current ask price is at or below the deepest
  included trigger and cash/risk checks pass, review/place one combined order
  with `quantity` equal to the sum of due lot shares. Do not stop after checking
  only a recent-DD subset.
- If full DD coverage remains incomplete because the fast path is blocked,
  broker payloads are too large or truncated, workspace permissions prevent
  required state reads/writes, or order history needed for lot reconstruction
  cannot be fetched, the market run is blocked. Start the report with exactly
  `DD SCAN BLOCKED`, include the exact blocker and which symbols were/weren't
  verified in the task transcript and automation memory, and do not report a
  routine no-action result. Regular-hours-only exact-share DDs and post-integer
  DD decimal leftovers are verified report-only items in lanes where they are
  not executable and must not be included in that blocker set.
- Use `data/runtime/dd-known-blockers.csv` as an ignored same-system cache for
  repeated non-executable DD noise. If the scan output reports
  `suppressed_dd_blockers_sample`, those rows were already seen with the same
  signature and should not be repeated in the blocker report/count. New or
  changed blockers must still be reported, and executable DDs must still be
  reviewed/placed normally.
- Do not keep scanning other symbols while an executable candidate is waiting.
- Do not write local ledger/state before execution.
- Do not write `data/private/sold-today.md` while sell execution is still in
  progress. After all sell orders from the run are placed and confirmed
  filled, append one pending-reopen row for each symbol that still needs
  reopen, including the sold date/time and any known blocked-reopen reason.
  After reopen buy orders are confirmed filled, remove those symbols from the
  file.
- For the post-sell tracking reopen exception, do not append a sold symbol to
  `sold-today.md` if the immediate tracking reopen has already been confirmed
  filled. If symbol policy blocks reopen, do not append it. If the immediate
  reopen is blocked for another reason, append or leave that symbol in
  `sold-today.md` for later reopening.
- Do not place real orders from the fast read-only scripts, and do not place
  orders in parallel. Use the broker review/place workflow for the single
  qualifying candidate.
- For new openings, compare `data/universe.csv` against live Robinhood
  positions and active orders. Do not use the local ledger as the owned-symbol
  source during market hours. Apply `data/symbol-policy.csv` before selecting
  opening candidates.
- After all executable sell/DD work and full owned-position checks are complete,
  update `data/private/top-10-buy-candidates.md` and
  `data/private/top-10-sell-candidates.md` from the latest positions and quotes
  as the last cleanup step.
- If the main half-hour scan finishes before the +15 mark and before 12:45 PT,
  wait until that +15 mark in the same thread and run a fast recheck. The
  recheck must quote the refreshed shortlist first, then use `FAST WATCH` or
  an equivalent live owned-position scan to confirm any sell/DD candidate. It
  must execute qualifying sell/DD immediately and must not place new openings.
- If the main scan finds or is processing an executable sell/DD candidate, do
  not wait for the +15 recheck. Execution remains priority one.
- If the main scan or recheck would run into 1:00 PM PT, stop regular-hours
  market work and leave extended-hours trading to the `13:00 PT - RH AH`
  automation.

Automations do not send email for any outcome. Record successful actions,
routine no-action checks, `OPEN CASH AVAILABLE`, blocked actions, incomplete DD
scans, guard exceptions, broker/tool failures, reconciliation failures, and
other attention-needed conditions in the task transcript and automation memory
only. An incomplete DD scan is not routine no-action; it remains a blocked scan
and must be labeled clearly in those reporting surfaces.

## Premarket Trading

The premarket trade slots run at `04:00`, `05:00`, and `06:00` Pacific on
weekdays. They use the same narrow extended-hours execution rules as the
after-hours slots.

The `06:00 PT - RH PRE` slot has an extra runtime boundary: stop new broker
reviews and placements by `06:25` Pacific and hard-stop all work before
`06:30` Pacific. If anything remains, leave a concise handoff instead of
continuing into the `06:30 PT - RH MKT` automation.

The `04:00 PT - RH PRE` and `05:00 PT - RH PRE` slots should cover most of the
hour with one in-thread `+30` recheck. If the first pass finishes before
`HH:30`, no executable whole-share sell/DD remains, and the next slot boundary
is not at risk, stay in the same thread, wait until `HH:30`, rerun the fresh
broker-backed scan/classifier, and execute any qualifying whole-share sell/DD
immediately. Do not run this recheck in the `06:00 PT - RH PRE` slot.

## After-Hours Trading

The after-hours trade slots run at `13:00`, `14:00`, `15:00`, and `16:00`
Pacific on weekdays. `13:00 PT - RH AH` is a trading lane, not a close
reconciliation lane.

Extended-hours execution scope is intentionally narrow:

- Use only live premarket/after-hours bid/ask prices for executable decisions.
  Do not use official close as the buy/sell execution price.
- For DDs, reconstruct the current lot ladder from broker filled orders. If the
  live extended-hours ask is at or below the deepest due trigger, place only
  the integer part of the combined due quantity as an extended-hours limit buy.
  Leave fractional leftovers unplaced, report them, and write/update
  `data/runtime/dd-fractional-leftovers.csv`. These leftovers are not DD scan
  blockers.
- `python -m agentic_strategy.afterhours_scan` also maintains
  `data/runtime/dd-known-blockers.csv` by default. Treat unchanged suppressed
  rows from that cache as already-known noise, not as fresh blocked coverage.
  The JSON keeps raw provenance blockers separately because they still block
  unsafe DD output and shortlist publication; only new or changed provenance
  blockers remain in the reportable blocker count and message.
  Do not use the cache to skip an executable whole-share sell/DD candidate.
- For sells, use live extended-hours bid as the sell-side executable price. If
  the integer sellable quantity is at least 1 share and bid-side return is at
  least 10%, place that integer quantity as an extended-hours limit sell. If
  the whole-share sell is confirmed filled and a fractional remainder is still
  sellable, queue the remainder as a regular-hours market sell.
- Do not place new openings, reopens, emergency-cash sells, or fractional
  extended-hours orders from these jobs.
- Stop new broker reviews and placements at or after 17:00 Pacific, the end of
  the standard Robinhood extended-hours window.
- If Robinhood returns a broker alert on review, do not place that order unless
  the alert is explicitly allowed by the automation prompt or the user has
  provided a direct override in the same run.

Each after-hours slot should cover most of the hour with one in-thread `+30`
recheck. If the first pass finishes before `HH:30`, no executable whole-share
sell/DD remains, and current time is still before `HH:30`, stay in the same
thread, wait until `HH:30`, rerun the fresh broker-backed scan/classifier, and
execute any qualifying whole-share sell/DD immediately. Do not run additional
rechecks after the `+30` pass, and stop before the next slot boundary.

New-opening buys remain report-only in automation runs unless the user
explicitly authorizes new openings in that run. The only standing reopen
exception is the immediate base tracking reopen after a confirmed profitable
sell fill during a market-hours automation run.

## Daily Summary

`17-00-pt-rh-daily-summary` runs every day at exactly 5:00 PM Pacific. It is a
read-only performance report and the standing daily local persistence window.
It must never place, review, cancel, prepare, or suggest orders.

It should:

- refresh Robinhood broker truth for the Agentic account
- fetch portfolio, positions, open/recent orders, queued orders, filled orders,
  cancellations, rejections, buying power, and cash
- fetch the Agentic account portfolio with
  `node scripts/rh_fast.mjs portfolio --account 878067701 --output data/runtime/daily-summary-portfolio.json`
- fetch positions with quotes with
  `node scripts/rh_fast.mjs positions --account 878067701 --with-quotes --output data/runtime/daily-summary-positions-quotes.json --summary-output data/runtime/daily-summary-positions.csv`
- fetch all equity orders with
  `node scripts/rh_fast.mjs orders --account 878067701 --all --output data/runtime/daily-summary-orders-all.json`
- import broker order history, fills, cancellations, rejections, and known
  skipped-action reasons into `data/private/order-ledger.csv`; this is audit
  history only
- generate `data/private/current-symbols.json`
- generate `data/private/close-summary.md`
- generate `data/private/top-10-buy-candidates.md`
- generate `data/private/top-10-sell-candidates.md`
- include up to 50 eligible open candidates by comparing `data/universe.csv`
  against the broker-derived owned and active-order symbols
- reconcile queued orders, fills, current positions, position sizes, buying
  power, and cash buffer status
- import user- or broker-canceled pending orders as cancellations rather than
  leaving them as active blockers
- if full position coverage is incomplete, still validate the top downside
  holdings as next-session DD watch candidates by reconstructing lot state and
  comparing current ask to `next_trigger_price`; report only, do not place
  orders during the daily summary
- if that downside/DD validation cannot complete, mark the daily report
  `DD SCAN BLOCKED` and include the exact blocker plus the symbols that were and
  were not verified in the task transcript and automation memory
- generate `data/private/daily-summary.md`,
  `data/private/daily-summary.json`, and
  `data/private/daily-return-cycles.csv`
- update `data/private/performance-history.csv` and regenerate
  `data/private/performance-history.md`; reruns for the same Pacific date must
  replace that date's row instead of appending duplicates
- use this command for the performance report and history:
  `python -m agentic_strategy.daily_summary --portfolio-json data/runtime/daily-summary-portfolio.json --positions-json data/runtime/daily-summary-positions-quotes.json --orders-json data/runtime/daily-summary-orders-all.json --output-md data/private/daily-summary.md --cycles-csv data/private/daily-return-cycles.csv --output-json data/private/daily-summary.json --history-csv data/private/performance-history.csv --history-md data/private/performance-history.md`

The report should highlight portfolio paper gain, portfolio paper loss, net
paper P/L, realized trading-day profit by Pacific hour, sell-cycle hold time
from first buy to sell, account value, cash, buying power, and any uncosted
sold quantity caused by incomplete order history.

The daily automation does not send email. Reconciliation blocks, broker access
failures, local ledger/cache update failures, blocked DD scan coverage, and
high-priority next-session candidates must be reported in the task transcript
and automation memory only.

## Weekly Symbol Policy Refresh

`weekly-rh-symbol-policy-refresh` runs Sunday morning off-market. It is a
policy maintenance job only.

It should:

- start by confirming it is weekend/off-market in Pacific time
- read `AGENTS.md`, `docs/automation-monitor.md`, and `docs/symbol-policy.md`
- run `node scripts/weekly_symbol_policy_refresh.mjs --run --account 878067701`
- run `python -m agentic_strategy.validate_symbol_policy --policy data/symbol-policy.csv`
- report the summary path, metrics path, policy row counts, newly filtered
  symbols, restored symbols, owned `no_reopen` count, and unowned `no_new_open`
  count

The refresh script uses Yahoo Finance as the primary historical source. If
Yahoo fetching fails for a symbol, it must fetch Robinhood historical daily bars
for that symbol before marking the symbol failed.

It must not:

- call broker order review or placement tools
- place, prepare, or suggest buy, sell, reopen, double-down, or emergency cash
  orders
- touch `data/private/sold-today.md`
- update `data/private/top-10-buy-candidates.md` or
  `data/private/top-10-sell-candidates.md`
- write `data/private/order-ledger.csv`
- regenerate `data/private/current-symbols.json`, `data/private/close-summary.md`,
  or deprecated `data/private/LIVE_STATE.md`

The refresh script replaces only auto-managed policy rows identified by the
weekly/yahoo intraday-range evidence and normal generated permissions. Manual
policy rows are preserved. If fewer than 95% of universe symbols are
successfully analyzed, the script writes audit artifacts but must not replace
`data/symbol-policy.csv`.

## Monthly Universe Discovery

`monthly-rh-universe-discovery` runs on the first Saturday of each month at
8:00 AM Pacific. It is a read-only universe and policy maintenance job only.

It should:

- start by confirming it is the first Saturday of the month, off-market, and
  at or after 8:00 AM Pacific
- read `AGENTS.md`, `docs/automation-monitor.md`, `docs/universe-management.md`,
  and `docs/symbol-policy.md`
- run `node scripts/monthly_universe_discovery.mjs --run --account 878067701`
- if accepted symbols were merged, run
  `node scripts/weekly_symbol_policy_refresh.mjs --run --account 878067701`
- run `python -m agentic_strategy.validate_symbol_policy --policy data/symbol-policy.csv`
- report candidate count, accepted count, rejected count, universe rows before
  and after, active/tradable/fractional universe count, policy row counts, and
  the summary artifact paths

The discovery script fetches Nasdaq Trader `nasdaqlisted.txt` and
`otherlisted.txt`, filters likely common-stock candidates not already in
`data/universe.csv`, validates candidates through Robinhood tradability, and
merges only active/tradable/fractional results. It preserves raw source files,
candidate rows, local filter rejections, broker validation rows, broker
rejections, and summaries under
`data/runtime/monthly-universe-discovery/<date>/`.

It must not:

- call broker order review or placement tools
- place, prepare, cancel, or suggest buy, sell, reopen, double-down, or
  emergency cash orders
- touch `data/private/sold-today.md`
- update `data/private/top-10-buy-candidates.md` or
  `data/private/top-10-sell-candidates.md`
- write `data/private/order-ledger.csv`
- regenerate `data/private/current-symbols.json`, `data/private/close-summary.md`,
  or deprecated `data/private/LIVE_STATE.md`

## Live Source Of Truth

Robinhood broker data is the live source of truth. The automation must inspect
the Agentic Robinhood account, positions, quotes, orders, and fills directly.
Do not use stale `data/private/order-ledger.csv` or
`data/private/current-symbols.json` data to decide whether to trade.

Do not import broker orders, write the local ledger, regenerate deprecated
`data/private/LIVE_STATE.md`, or save raw broker payloads during market-hours
execution unless the user explicitly asks for local persistence in that exact
run. Updating the top-10 shortlist files at the end of a market-hours run is
allowed as cleanup only after executable work is complete. Updating
`data/private/sold-today.md` after confirmed sell fills or confirmed reopen
fills is also allowed because it is the durable pending-reopen queue, but it
must never delay a qualifying market-hours sell or double-down order. The 5 PM
daily automation is the standing exception and should update the audit ledger,
`data/private/current-symbols.json`, `data/private/close-summary.md`, and both
shortlist files. Local audit/cache writes must never delay a qualifying
market-hours sell or double-down order.

## Trading Boundary

The market-hours automation must not place real orders unless the active broker
tool workflow allows it. The market monitor has standing user authorization for
qualifying sell orders, double-down orders, and immediate base tracking reopens
after confirmed profitable sell fills, so it should not wait for chat
confirmation when the broker review is clean. It must still obey broker/tool
blocks and must not claim an order was placed unless the broker placement call
actually succeeded.

The 5 PM daily automation must never place real orders. It is for summary and
local persistence only.

If persistence was explicitly requested and fails, report the exact path and
error. Continue with live broker reporting, but clearly say the optional local
audit write was not updated.
