# Open Questions And Resolved Decisions

Resolve these before production automation places many live orders.

## Resolved: Start-Price Cap

Decision: there is no share-price cap for opening positions.

Reason: stocks priced at `$1.00` or higher can use fractional dollar sizing, so
there is no share-price cap for openings. The real cap is available deployable
cash after preserving the 10% cash buffer and satisfying any higher-priority
double-down obligations.

Operational implication: if roughly 5,000 Robinhood-tradable stocks are eligible,
the `$1` base round needs about `$5,000` of opening capital before moving to a
`$2` base round, then `$3`, `$4`, and so on.

## Resolved: Complete Universe Source

Decision: build and maintain our own local Robinhood-validated stock universe.
The canonical file is `data/universe.csv`.

Reason: the current tools may not provide a complete Robinhood-tradable universe
endpoint. The user will provide symbols over time, and future agents should
confirm each symbol on Robinhood before adding it to the canonical list.

Operational workflow:

- User supplies candidate symbols from any source.
- Agent checks Robinhood tradability and eligibility in batches.
- Confirmed active/tradable symbols are added or refreshed in `data/universe.csv`.
- Delisted, inactive, or non-tradable symbols are marked inactive/non-tradable
  rather than silently deleted.
- The trading engine only opens positions from this local validated universe.

## Resolved: Exact Lot Ladder

Decision: the base buy is lot 1. After that, each new lot doubles the previous
lot's share count and uses a drop trigger from the previous trigger price.

Lot trigger zones:

- Lots 2-5: 10% drop, 4 buys total after the base.
- Lots 6-10: 20% drop, 5 buys total.
- Lots 11-15: 40% drop, 5 buys total.
- Lots 16 and beyond: 80% drop, continuing in 5-buy 80% zones as long as the
  stock remains tradable and cash/risk rules allow it.

Reason: the ladder can theoretically continue indefinitely because each 80%
drop moves the next trigger price closer to zero. In practice, a stock will
likely be delisted, hit the 10% profit sell rule, hit the 10% position cap, or
run into cash constraints long before many 80% drops occur.

## Resolved: Target Sell Execution And Order Sizing

Decision: strategy orders use immediate market execution when criteria are met.
Do not design broker-side GTC limit target exits for this strategy.

Reason: the strategy is built around fractional dollar-based positions, and the
operating assumption is that fractional buys and sells cannot use limit orders.
The execution system should monitor criteria and submit market orders when a
sell, double-down, emergency green sell, open, or reopen rule is met.

Sizing clarification:

- Stocks priced at `$1.00` or higher use dollar-based fractional sizing.
- Stocks priced below `$1.00` use whole-share quantity sizing.
- Sub-dollar penny stocks should not be bought fractionally.
- For sub-dollar stocks, use the whole-share quantity that fits within the
  target lot dollars, with a minimum of 1 whole share.

Operational implication: the user does not want to manually monitor orders. The
intended production behavior is automatic market execution once strategy
criteria are satisfied. If the active broker or agent tool still requires order
review or explicit confirmation at runtime, implementation must obey that as an
external tool constraint, not as a strategy preference.

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
