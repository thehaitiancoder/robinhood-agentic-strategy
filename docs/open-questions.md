# Open Questions And Resolved Decisions

Resolve these before production automation places many live orders.

## Resolved: Start-Price Cap

Decision: there is no share-price cap for opening positions.

Reason: the strategy uses fractional dollar orders. A high-priced stock can
still be opened with a `$1` base position. The real cap is available deployable
cash after preserving the 10% cash buffer and satisfying any higher-priority
double-down obligations.

Operational implication: if roughly 5,000 Robinhood-tradable stocks are eligible,
the `$1` base round needs about `$5,000` of opening capital before moving to a
`$2` base round, then `$3`, `$4`, and so on.

## Complete Universe Source

The current tools can search symbols and check tradability, but a complete
Robinhood-tradable stock universe has not been confirmed.

Decision needed: choose the canonical universe source.

Options:

- User-provided export.
- Robinhood watchlist/list data if complete enough.
- Third-party market data provider, then validate each symbol with Robinhood.
- Broker/API endpoint if later available.

## Exact Lot Ladder

The screenshot shows drop zones of 10%, then 20%, then 40%, and a final larger
drop. Confirm exact lot ranges and whether the final 80% step is still part of
the production strategy.

## Target Sell Execution

For tiny fractional positions, broker-native persistent target exits may not be
available through current tools. Confirm preferred behavior:

- Active monitor with sell review and confirmation.
- GTC limit orders when supported.
- Mixed mode: broker-native exits for whole shares, monitor for fractional
  positions.

## Resolved: Emergency Green Sells

Decision: when cash is needed for double-downs, rank green positions below 10%
profit by highest positive return first.

Reason: the strategy should free cash from the strongest available green
positions first, even if they have not reached the full 10% profit target.

Rejected ranking factors for this rule: largest market value, distance from 10%,
and oldest position.

## Resolved: Taxes and Wash Sales

Decision: do not apply wash-sale cooldowns, tax-aware reopening blocks, or
tax-adjusted cost basis to strategy decisions.

Reason: the strategy needs the real trade fill price and actual dollars invested
to remain visible. A broker-side wash-sale cost-basis adjustment can hide the
real buy price and distort the ladder. The operating assumption is that
Robinhood tax reporting is handled separately from this strategy ledger, so this
system should not change trading behavior for tax reasons.

Operational implication: the strategy ledger may keep fills and realized
gain/loss records for audit and reporting, but tax lots and wash-sale rules must
not block openings, reopenings, double-downs, or target sells.
