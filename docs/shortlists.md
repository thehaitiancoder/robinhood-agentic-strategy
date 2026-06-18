# Candidate Shortlists

The strategy keeps two ignored Markdown shortlist files:

- `data/private/top-10-buy-candidates.md`
- `data/private/top-10-sell-candidates.md`

They are speed hints from the previous run. They are not source-of-truth trading
state. Refresh Robinhood before reviewing or placing any order.

## Purpose

Most sell or double-down opportunities are likely to come from positions that
were already near the top or bottom of return ranking in the prior run. A new
agent should check these symbols first before doing the full owned-position
scan.

## Meaning

- Top 10 buy candidates: owned positions with the worst buy-side return from
  the last recorded quote. During market hours this is ask-side return; when
  the regular market is closed, the speed hint uses official close first, then
  non-regular/last price fallbacks. These are likely double-down watch symbols.
- Top 10 sell candidates: owned positions with the best bid-side return from
  the last recorded quote. These are likely target-sell watch symbols.

The DD decision still requires strategy ladder math and a fresh broker quote.
If a DD qualifies, the broker review/place call must use share `quantity`, not a
rounded `dollar_amount`. If multiple same-symbol DD lots are due at the current
ask, combine those due lot shares into one order. A DD may be placed only if
the fresh broker ask is at or below the deepest included trigger; after
placement, immediately cancel an active DD order if the returned broker `price`
or `average_price` is missing or above that trigger. If Robinhood rejects the
fractional DD quantity, retry the integer part only when it is at least 1
share. The sell decision still requires bid-side 10% return math and a fresh
broker quote.

If a full owned-position scan is incomplete or tool payloads truncate, the top
buy/downside shortlist becomes mandatory DD verification input. Any shortlisted
or partially scanned owned symbol shown at `<= -10%` return with no active buy
order must be checked directly: fetch filled buys/orders, reconstruct the next
and any subsequent same-symbol due lots, refresh the quote, and compare current
ask against the deepest included trigger. Only place if the exact ladder, cash,
concentration, and broker checks pass.

## Timing

At the start of a market-hours run:

1. Read both shortlist files if they exist.
2. Quote those symbols first through Robinhood. With the fast helper, use:
   `node scripts/rh_fast.mjs quotes --file data/private/top-10-sell-candidates.md`
   and `node scripts/rh_fast.mjs quotes --file data/private/top-10-buy-candidates.md`.
3. If one qualifies for sell or DD, execute/review it immediately.
4. Do not start `FAST WATCH`, `positions --with-quotes`, or another broad
   owned-position scan until the shortlist quote/review step is complete and
   no shortlisted symbol qualifies.
5. If no shortlist symbol qualifies, continue the full owned-position scan.
6. If that full scan cannot complete, do not stop after a recent-DD subset.
   Directly verify the top downside holdings and any exposed `<= -10%` owned
   positions with no active buy order before reporting no DD due.

At the end of a run:

1. Only after all executable sell/DD work is finished, update both shortlist
   files from the latest positions and quotes.
2. Do not update shortlists while an executable candidate is waiting.
3. Do not update the audit ledger or deprecated `LIVE_STATE.md` as part of this
   cleanup.

## Command

After saving fresh broker positions and quotes under `data/private/latest/`,
run:

```bash
PYTHONPATH=src python -m agentic_strategy.shortlists \
  --positions-json data/private/latest/positions.json \
  --quotes-json data/private/latest/quotes.json \
  --buy-output data/private/top-10-buy-candidates.md \
  --sell-output data/private/top-10-sell-candidates.md
```

The files are ignored by git because they contain broker-derived position and
quote data.
