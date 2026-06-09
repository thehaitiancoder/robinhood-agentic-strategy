# Codex Automation Monitor

Automation ids:

- `robinhood-strategy-market-monitor`
- `robinhood-strategy-1-pm-close-check`

Visible automation names:

- `RH MKT 30m`
- `RH 1PM close`

Purpose: run the strategy priority loop during regular market hours without the
user needing to manually remember checks, and execute qualifying sell and
double-down orders quickly when they are due.

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

- Each automation prompt starts by instructing the run to rename its Codex
  thread with the current Pacific date/time followed by a short label.
- Expected format: `MM-DD HH:mm PT - RH MKT` or
  `MM-DD HH:mm PT - RH CLOSE`.
- The timestamp must be at the beginning of the title, not appended to the end,
  because mobile chat lists truncate long titles.
- Keep this instruction near the beginning of each automation prompt; otherwise
  the chat list fills with repeated indistinguishable monitor titles.

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

## Execution And Email Behavior

The automation checks in this order:

1. sell targets at or above 10% return
2. due double-downs
3. emergency green-sell candidates if double-down cash is short
4. deployable idle cash for new openings
5. routine queued orders, open positions, and stale-data status

The user has standing-authorized the automations to place qualifying strategy
sell and double-down orders directly, subject to broker tool review and
placement constraints. Speed is priority number one for executable sell and
double-down candidates.

Execution rules:

- Process one executable sell or double-down candidate at a time.
- Refresh the quote immediately before order review.
- If the broker tool requires review, run the review immediately.
- If the review has no blocking alerts and the refreshed price still qualifies,
  place the market order immediately.
- Do not keep scanning other symbols while an executable candidate is waiting.
- Do not write local ledger/state before execution.

It emails `rdgustave@gmail.com` only for urgent execution outcomes:

- `URGENT SELL EXECUTED - Robinhood strategy`
- `URGENT SELL BLOCKED - Robinhood strategy`
- `DOUBLE-DOWN EXECUTED - Robinhood strategy`
- `DOUBLE-DOWN BLOCKED - Robinhood strategy`

It does not email routine no-action checks or `OPEN CASH AVAILABLE` by default.

New-opening buys remain report-only in automation runs unless the user
explicitly authorizes new openings in that run.

## Live Source Of Truth

Robinhood broker data is the live source of truth. The automation must inspect
the Agentic Robinhood account, positions, quotes, orders, and fills directly.
Do not use stale `data/private/order-ledger.csv` or
`data/private/LIVE_STATE.md` data to decide whether to trade.

Do not import broker orders, regenerate `data/private/LIVE_STATE.md`, write the
local ledger, or save raw broker payloads unless the user explicitly asks for
local persistence in that exact run. Local audit writes must never delay a
qualifying sell or double-down order.

## Trading Boundary

The automation must not place real orders unless the active broker tool
workflow allows it. The recurring automations have standing user authorization
for qualifying sell and double-down orders, so they should not wait for chat
confirmation when the broker review is clean. They must still obey broker/tool
blocks and must not claim an order was placed unless the broker placement call
actually succeeded.

If persistence was explicitly requested and fails, report the exact path and
error. Continue with live broker reporting, but clearly say the optional local
audit write was not updated.
