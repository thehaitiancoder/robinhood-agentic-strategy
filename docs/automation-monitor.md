# Codex Automation Monitor

Automation id: `robinhood-strategy-market-monitor`

Purpose: run the strategy priority loop during regular market hours without the
user needing to manually remember checks.

Schedule: weekdays every 30 minutes from 6:00 AM through 1:30 PM Pacific. The
6:00 AM run is an early pre-open check; market open is covered at 6:30 AM.

Model settings:

- Model: `gpt-5.4`
- Reasoning effort: `xhigh`

Writable roots configured for the automation:

- `C:\Users\ralph\.codex\worktrees\de6e\robinhood-agentic-strategy`
- `C:\Users\ralph\.codex\automations\robinhood-strategy-market-monitor`

The repo root covers:

- `data/private/order-ledger.csv`
- `data/private/LIVE_STATE.md`
- repo-local skipped-action logging
- saved broker payload snapshots under `data/private/`

The automation directory covers automation-local memory/state files such as
`memory.md`. If a run reports that this path is read-only, update the automation
configuration to include that directory as a writable root or approve a one-time
escalated write for the memory file.

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
- Give it write access to
  `C:\Users\ralph\.codex\automations\robinhood-strategy-market-monitor` for
  automation memory/state.
