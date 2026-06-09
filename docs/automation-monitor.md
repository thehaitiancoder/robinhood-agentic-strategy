# Codex Automation Monitor

Automation ids:

- `robinhood-strategy-market-monitor`
- `robinhood-strategy-1-pm-close-check`

Visible automation names:

- `RH MKT 30m`
- `RH 1PM close`

These names are static scheduler labels. They cannot include the current run
time. The visible per-run chat name must be set by renaming the thread at run
startup.

Purpose: run the strategy priority loop during regular market hours without the
user needing to manually remember checks, execute qualifying sell and
double-down orders quickly before the market closes, then run a 1:00 PM Pacific
post-market reconciliation that updates local state.

Schedule:

- `robinhood-strategy-market-monitor`: weekdays every 30 minutes from 6:00 AM
  through 12:30 PM Pacific.
- `robinhood-strategy-1-pm-close-check`: weekdays at exactly 1:00 PM Pacific.

The automation scheduler currently stores and honors the RRULE `BYHOUR` values
as UTC, even though the UI displays local time. Do not configure these as
Pacific-local `BYHOUR=6,7,8,9,10,11,12,13`; that caused late-night Pacific
runs around 11:00 PM, 11:30 PM, and midnight. Current intended UTC encodings
for Pacific daylight time are:

- main monitor: `BYHOUR=13,14,15,16,17,18,19;BYMINUTE=0,30`
- 1 PM close check: `BYHOUR=20;BYMINUTE=0`

If Pacific standard time is in effect and the scheduler still uses UTC fields,
adjust these UTC hours by one hour so the displayed next-run times remain
inside 6:00 AM through 1:00 PM Pacific.

Thread titles:

- Each automation prompt must start by instructing the run to call the Codex
  `set_thread_title` tool before reading files or checking Robinhood.
- The title must use the current Pacific date/time followed by a short label.
- Expected format: `MM-DD HH:mm PT - RH MKT` or
  `MM-DD HH:mm PT - RH CLOSE`.
- The timestamp must be at the beginning of the title, not appended to the end,
  because mobile chat lists truncate long titles.
- Keep this as the first action in each automation prompt; otherwise the chat
  list can show the static automation name, such as `RH MKT 30m`, instead of
  `06-09 09:00 PT - RH MKT`.

Model settings:

- Model: `gpt-5.4`
- Reasoning effort: `xhigh`

Workspace configuration:

- `C:\Users\ralph\.codex\worktrees\de6e\robinhood-agentic-strategy`

Keep the `cwds` field to this single repo root only. In the Codex automation
tool, `cwds` are runnable workspaces, not generic writable roots. Adding
`C:\Users\ralph\.codex\automations\...` as a second `cwd` causes the same
automation run to create a duplicate thread in the automation directory.

Do not add a second writable automation directory as another `cwd`. If an
automation needs persistent memory outside the repo, configure that as an
automation setting rather than another runnable workspace.

## Market Monitor Execution

`robinhood-strategy-market-monitor` runs during regular market hours and checks
in this order:

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

- Read `data/private/top-10-sell-candidates.md` and
  `data/private/top-10-buy-candidates.md` if present, then quote those symbols
  first through Robinhood. These are speed hints only.
- Process one executable sell or double-down candidate at a time.
- Refresh the quote immediately before order review.
- If the broker tool requires review, run the review immediately.
- If the review has no blocking alerts and the refreshed price still qualifies,
  place the market order immediately.
- Do not keep scanning other symbols while an executable candidate is waiting.
- Do not write local ledger/state before execution.
- For new openings, compare `data/universe.csv` against live Robinhood
  positions and active orders. Do not use the local ledger as the owned-symbol
  source during market hours.
- After all executable sell/DD work and full owned-position checks are complete,
  update `data/private/top-10-buy-candidates.md` and
  `data/private/top-10-sell-candidates.md` from the latest positions and quotes
  as the last cleanup step.

It emails `rdgustave@gmail.com` only for urgent execution outcomes:

- `URGENT SELL EXECUTED - Robinhood strategy`
- `URGENT SELL BLOCKED - Robinhood strategy`
- `DOUBLE-DOWN EXECUTED - Robinhood strategy`
- `DOUBLE-DOWN BLOCKED - Robinhood strategy`

It does not email routine no-action checks or `OPEN CASH AVAILABLE` by default.

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
- produce a concise close summary in Codex

If a sell or double-down candidate is found at or after 1:00 PM Pacific, report
it as a next-market-session candidate only. Do not review or place an order from
the close automation.

The close automation does not email routine no-action summaries by default. It
emails `rdgustave@gmail.com` only if reconciliation is blocked, broker access
fails, local ledger/cache update fails, or a high-priority next-session
candidate is detected after the market has closed.

## Live Source Of Truth

Robinhood broker data is the live source of truth. The automation must inspect
the Agentic Robinhood account, positions, quotes, orders, and fills directly.
Do not use stale `data/private/order-ledger.csv` or
`data/private/current-symbols.json` data to decide whether to trade.

Do not import broker orders, write the local ledger, regenerate deprecated
`data/private/LIVE_STATE.md`, or save raw broker payloads during market-hours
execution unless the user explicitly asks for local persistence in that exact
run. Updating the top-10 shortlist files at the end of a market-hours run is
allowed as cleanup only after executable work is complete. The 1 PM close
automation is the standing exception and should update the audit ledger,
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
