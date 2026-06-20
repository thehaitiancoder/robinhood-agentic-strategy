# Deprecated Live State Snapshot

`data/private/LIVE_STATE.md` is deprecated.

It was a Markdown handoff file for queued orders, active orders, positions, and
ledger counts. In practice it became stale and encouraged agents to spend
market-hours time refreshing local files before acting.

Do not use `LIVE_STATE.md` as the source of truth for trading decisions.

Current model:

- Robinhood broker data is the source of truth during market hours.
- `data/private/order-ledger.csv` is post-market audit history only.
- `data/private/current-symbols.json` is a post-market planning cache only.
- `data/private/close-summary.md` is the human-readable close summary.

Use `docs/current-symbols.md` for the current post-market cache workflow.
