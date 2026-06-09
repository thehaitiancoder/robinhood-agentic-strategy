# Codex Automation Monitor

Automation ids:

- `robinhood-strategy-market-monitor`
- `robinhood-strategy-1-pm-close-check`

Purpose: run the strategy priority loop during regular market hours without the
user needing to manually remember checks.

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

Model settings:

- Model: `gpt-5.4`
- Reasoning effort: `xhigh`

Writable roots configured for the automation:

- `C:\Users\ralph\.codex\worktrees\de6e\robinhood-agentic-strategy`
- `C:\Users\ralph\.codex\automations\robinhood-strategy-market-monitor`
- `C:\Users\ralph\.codex\automations\robinhood-strategy-1-pm-close-check`

The repo root covers:

- `data/private/order-ledger.csv`
- `data/private/LIVE_STATE.md`
- repo-local skipped-action logging
- saved broker payload snapshots under `data/private/`

The automation directories cover automation-local memory/state files such as
`memory.md`. If a run reports that one of these paths is read-only, update that
automation configuration to include its directory as a writable root or approve
a one-time escalated write for the memory file.

## Alert Behavior

The automation checks in this order:

1. sell targets at or above 10% return
2. due double-downs
3. emergency green-sell candidates if double-down cash is short
4. deployable idle cash for new openings
5. routine queued orders, open positions, and stale-data status

It emails `rdgustave@gmail.com` only for:

- `URGENT SELL TARGET FOUND`
- `DOUBLE-DOWN DUE`

It does not email routine no-action checks or `OPEN CASH AVAILABLE` by default.

## Trading Boundary

The automation must not place real orders unless the active broker tool workflow
allows it. With the current Robinhood tool, real order placement requires broker
review plus explicit user confirmation. The automation may identify candidates,
prepare summaries, and send alerts; it must not claim an order was placed unless
the broker placement call actually succeeded.

## If Persistence Fails

If a run can read Robinhood but cannot write local state, the agent must report
the exact path and error. It should still provide read-only broker findings, but
it must clearly say that the audit trail was not updated.

Known fix:

- Give the automation write access to the repo root for repo-local state.
- Give it write access to its automation-local directory for memory/state:
  `C:\Users\ralph\.codex\automations\robinhood-strategy-market-monitor` or
  `C:\Users\ralph\.codex\automations\robinhood-strategy-1-pm-close-check`.
