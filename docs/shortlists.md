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

- Top 10 buy candidates: owned positions with the worst ask-side return from
  the last recorded quote. These are likely double-down watch symbols.
- Top 10 sell candidates: owned positions with the best bid-side return from
  the last recorded quote. These are likely target-sell watch symbols.

The DD decision still requires strategy ladder math and a fresh broker quote.
The sell decision still requires bid-side 10% return math and a fresh broker
quote.

## Timing

At the start of a market-hours run:

1. Read both shortlist files if they exist.
2. Quote those symbols first through Robinhood.
3. If one qualifies for sell or DD, execute/review it immediately.
4. If no shortlist symbol qualifies, continue the full owned-position scan.

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
