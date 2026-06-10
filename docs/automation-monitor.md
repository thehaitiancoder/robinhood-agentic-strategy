# Codex Automation Monitor

Automation ids:

- Market-hours half-hour entry slots:
  - `06-00-pt-rh-mkt`
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
- `robinhood-strategy-1-pm-close-check`
- `robinhood-strategy-market-monitor` is a paused legacy combined monitor.

Visible automation names:

- Market-hours entry slots use `HH:mm PT - RH MKT`, for example
  `09:00 PT - RH MKT`.
- `13:00 PT - RH CLOSE`
- The paused legacy combined monitor is named `RH MKT 30m PAUSED`.

These names are static scheduler labels. They cannot include the current run
date, and dynamic thread-title tools have not been reliably available inside
automation runs. The market monitor uses fixed half-hour entry slots so the
visible mobile chat-list title starts with the entry time even when runtime
thread renaming is unavailable. The +15 minute recheck happens inside the
preceding half-hour thread.

Purpose: run the strategy priority loop during regular market hours without the
user needing to manually remember checks, execute qualifying sell and
double-down orders quickly before the market closes, then run a 1:00 PM Pacific
post-market reconciliation that updates local state.

Schedule:

- Market-hours entry automations: weekdays every 30 minutes from 6:00 AM
  through 12:30 PM Pacific.
- Each entry automation performs its normal priority loop first. If no
  executable sell/DD remains and the +15 minute mark for that slot is still in
  the future, it waits in the same thread and runs a fast +15 minute sell/DD
  recheck. Example: `10:30 PT - RH MKT` performs the 10:30 check, then covers
  the 10:45 recheck inside the same thread.
- `robinhood-strategy-1-pm-close-check`: weekdays at exactly 1:00 PM Pacific.

Observed scheduler limitation: on 2026-06-10 the newly-created standalone
quarter-hour jobs `10-45-pt-rh-mkt` and `11-15-pt-rh-mkt` did not run, while
`11-00-pt-rh-mkt`, `11-30-pt-rh-mkt`, and the older 00/30 jobs did run. The
Codex manual documents custom cron cadence but does not document a minimum
interval. Until retested, use the half-hour entry plus in-thread +15 recheck
design for practical 15-minute market coverage.

Observed late-start behavior: on 2026-06-10, after the market-slot prompts had
been edited after their scheduled times, `06-00-pt-rh-mkt` launched again at
about 13:00 PT beside the close automation. The run obeyed the cutoff and
placed no orders, but it created a confusing extra thread. To contain this,
every market-hours prompt must begin with a hard local-Pacific time gate before
reading docs or calling Robinhood. The valid window is the entry slot through
25 minutes after the slot, never at or after 13:00 PT. Outside that window,
write only a concise late-start skip to automation memory if possible and stop.

The automation scheduler currently stores and honors the RRULE `BYHOUR` values
as UTC, even though the UI displays local time. Do not configure these as
Pacific-local `BYHOUR=6,7,8,9,10,11,12,13`; that caused late-night Pacific
runs around 11:00 PM, 11:30 PM, and midnight. Current intended UTC encodings
for Pacific daylight time are:

- market slots:
  - 06:00 PT: `BYHOUR=13;BYMINUTE=0`
  - 06:30 PT: `BYHOUR=13;BYMINUTE=30`
  - 07:00 PT: `BYHOUR=14;BYMINUTE=0`
  - 07:30 PT: `BYHOUR=14;BYMINUTE=30`
  - 08:00 PT: `BYHOUR=15;BYMINUTE=0`
  - 08:30 PT: `BYHOUR=15;BYMINUTE=30`
  - 09:00 PT: `BYHOUR=16;BYMINUTE=0`
  - 09:30 PT: `BYHOUR=16;BYMINUTE=30`
  - 10:00 PT: `BYHOUR=17;BYMINUTE=0`
  - 10:30 PT: `BYHOUR=17;BYMINUTE=30`
  - 11:00 PT: `BYHOUR=18;BYMINUTE=0`
  - 11:30 PT: `BYHOUR=18;BYMINUTE=30`
  - 12:00 PT: `BYHOUR=19;BYMINUTE=0`
  - 12:30 PT: `BYHOUR=19;BYMINUTE=30`
- 1 PM close check: `BYHOUR=20;BYMINUTE=0`

If Pacific standard time is in effect and the scheduler still uses UTC fields,
adjust these UTC hours by one hour so the displayed next-run times remain
inside 6:00 AM through 1:00 PM Pacific.

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
- The 1 PM close automation name is `13:00 PT - RH CLOSE`; its first visible
  response should start with `MM-DD 13:00 PT - RH CLOSE`.
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
2. due double-downs
3. emergency green-sell candidates if double-down cash is short
4. deployable idle cash for new openings
5. routine queued orders, open positions, and stale-data status

The user has standing-authorized the market monitor to place qualifying strategy
sell and double-down orders directly, subject to broker tool review and
placement constraints. Speed is priority number one for executable sell and
double-down candidates.

Execution rules:

- First action: check current Pacific time before reading docs, querying
  Robinhood, or writing repo state. If the run started outside its slot-valid
  window or at/after 13:00 PT, stop immediately with a late-start skip. Do not
  perform broker scans, order reviews, order placement, sold-today updates,
  shortlist updates, or other market-hour persistence from a late-started
  market slot.
- On the first market-hours run of the Pacific trading day, reset
  `data/private/sold-today.md`. If the helper sees a stale date, it resets the
  file automatically.
- Read `data/private/top-10-sell-candidates.md` and
  `data/private/top-10-buy-candidates.md` if present, then quote those symbols
  first through Robinhood. These are speed hints only.
- Fast read-only scripts from `docs/fast-mcp-workflows.md` may be used to speed
  broad quotes, positions, orders, and watch scans when available.
- Process one executable sell or double-down candidate at a time.
- Refresh the quote immediately before order review.
- If the broker tool requires review, run the review immediately.
- If the review has no blocking alerts and the refreshed price still qualifies,
  place the market order immediately.
- If Robinhood or the exchange shows a symbol is halted, paused, frozen, in a
  volatility pause, or otherwise not currently accepting orders, do not place a
  market order for that symbol. Treat the frozen displayed quote as stale for
  execution. If the symbol would otherwise qualify for a sell or DD, report the
  trade as broker-blocked by the halt, email the matching blocked sell/DD
  subject, and re-check after trading resumes. If it is not an executable
  candidate, skip it with the halt reason and continue the priority loop.
- If the user says they canceled a pending order, refresh live Robinhood order
  state before using that symbol in active-order blocking logic. A broker
  state of canceled, rejected, failed, expired, or any other non-active terminal
  state no longer blocks DD/opening decisions. A still-confirmed, queued, new,
  unconfirmed, or partially-filled order remains active and blocks another buy
  for the same symbol.
- For double-downs, review and place the order with the broker `quantity` set
  to the exact `next_lot_shares` value from the ladder. Do not place DDs with a
  rounded `dollar_amount`; dollar values are estimates for cash and risk checks
  only.
- If the full live position basket cannot be exhaustively scanned, the monitor
  must still validate the top downside holdings directly before reporting no
  DD. Any owned symbol shown by the top downside shortlist, a partial broker or
  fast scan, or other current broker-backed evidence at `<= -10%` return and
  with no active buy order is a mandatory DD verification candidate. Fetch the
  filled buy/order history needed to reconstruct current lot state, calculate
  `next_lot_shares` and `next_trigger_price`, refresh the live quote, and if
  current ask price is at or below the trigger and cash/risk checks pass,
  review/place immediately with `quantity=next_lot_shares`. Do not stop after
  checking only a recent-DD subset.
- If full DD coverage remains incomplete because the fast path is blocked,
  broker payloads are too large or truncated, workspace permissions prevent
  required state reads/writes, or order history needed for lot reconstruction
  cannot be fetched, the market run is blocked. Start the report with exactly
  `DD SCAN BLOCKED`, email `rdgustave@gmail.com`, include the exact blocker and
  which symbols were/weren't verified, and do not report a routine no-action
  result.
- Do not keep scanning other symbols while an executable candidate is waiting.
- Do not write local ledger/state before execution.
- Do not write `data/private/sold-today.md` while sell execution is still in
  progress. After all sell orders from the run are placed and confirmed
  filled, append only the sell time and symbol to that file for symbols that
  still need reopen. After reopen buy orders are confirmed filled, remove those
  symbols from the file.
- Do not place real orders from the fast read-only scripts, and do not place
  orders in parallel. Use the broker review/place workflow for the single
  qualifying candidate.
- For new openings, compare `data/universe.csv` against live Robinhood
  positions and active orders. Do not use the local ledger as the owned-symbol
  source during market hours.
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
- If the main scan or recheck would run into 1:00 PM PT, stop trading work and
  leave post-market persistence to the close automation.

It emails `rdgustave@gmail.com` only for urgent execution outcomes:

- `URGENT SELL EXECUTED - Robinhood strategy`
- `URGENT SELL BLOCKED - Robinhood strategy`
- `DOUBLE-DOWN EXECUTED - Robinhood strategy`
- `DOUBLE-DOWN BLOCKED - Robinhood strategy`
- `DOUBLE-DOWN SCAN BLOCKED - Robinhood strategy`

It does not email routine no-action checks or `OPEN CASH AVAILABLE` by default.
An incomplete DD scan is not routine no-action; it is a blocked scan and must
email.

New-opening buys remain report-only in automation runs unless the user
explicitly authorizes new openings in that run.

## 1 PM Close Reconciliation

`robinhood-strategy-1-pm-close-check` runs at exactly 1:00 PM Pacific. At that
time regular market hours are closed, so this automation must not place buy
orders, sell orders, double-down orders, emergency-cash sells, or new-opening
orders.

The 1 PM close automation is the standing daily local persistence window. It
should:

- refresh Robinhood broker truth for the Agentic account
- fetch portfolio, positions, open/recent orders, queued orders, filled orders,
  cancellations, rejections, buying power, and cash
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
  orders after close
- if that downside/DD validation cannot complete, mark the close report
  `DD SCAN BLOCKED`, email `rdgustave@gmail.com` with subject
  `DOUBLE-DOWN SCAN BLOCKED - Robinhood strategy`, and include the exact
  blocker plus the symbols that were and were not verified
- produce a concise close summary in Codex

If a sell or double-down candidate is found at or after 1:00 PM Pacific, report
it as a next-market-session candidate only. Do not review or place an order from
the close automation.

The close automation does not email routine no-action summaries by default. It
emails `rdgustave@gmail.com` only if reconciliation is blocked, broker access
fails, local ledger/cache update fails, DD scan coverage is blocked, or a
high-priority next-session candidate is detected after the market has closed.

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
fills is also allowed because it is the daily sold-not-reopened queue, but it
must never delay a qualifying market-hours sell or double-down order. The 1 PM
close automation is the standing exception and should update the audit ledger,
`data/private/current-symbols.json`, `data/private/close-summary.md`, and both
shortlist files. Local audit/cache writes must never delay a qualifying
market-hours sell or double-down order.

## Trading Boundary

The market-hours automation must not place real orders unless the active broker
tool workflow allows it. The market monitor has standing user authorization for
qualifying sell and double-down orders, so it should not wait for chat
confirmation when the broker review is clean. It must still obey broker/tool
blocks and must not claim an order was placed unless the broker placement call
actually succeeded.

The 1 PM close automation must never place real orders. It is for summary and
local persistence only.

If persistence was explicitly requested and fails, report the exact path and
error. Continue with live broker reporting, but clearly say the optional local
audit write was not updated.
