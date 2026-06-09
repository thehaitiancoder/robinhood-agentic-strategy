# Open Questions

Resolve these before production automation places many live orders.

## Start-Price Cap

The user described a previous hard `$20` start-price rule and said violating it
with a `$73` opening position was a fatal mistake. The new strategy statement
also says "buy every single stock available on Robinhood."

Decision needed: should the restored strategy enforce a max share price for new
positions, such as `$20`, or should fractional `$1` openings apply to higher
priced stocks too?

Conservative default until confirmed: enforce the `$20` cap for new positions.

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

## Emergency Green Sells

When cash is needed for double-downs, define how to rank green positions below
10% profit.

Candidate ranking:

1. Highest positive return.
2. Largest market value.
3. Least likely to hit 10% soon.
4. Oldest position.

## Taxes and Wash Sales

The strategy may create many short-term trades and possible wash-sale effects.
This project should track tax lots and realized gains/losses for reporting, but
it is not a tax advisor.

