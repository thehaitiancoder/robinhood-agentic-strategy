# Robinhood Tooling Notes

These notes describe the agent tools observed during setup. Future agents should
verify tool schemas at runtime because capabilities can change.

## Current Useful Capabilities

- List brokerage accounts.
- Get portfolio value, cash, and buying power.
- List equity positions.
- Get quotes for one or more stock symbols.
- Check equity tradability for symbols.
- Review an equity order before placement.
- Place an equity order after required confirmation.
- Fetch equity order history.
- Cancel open equity orders after confirmation.

## Current Gaps

- No confirmed complete endpoint for "all Robinhood-tradable stocks."
- No confirmed autonomous bracket order support through the current agent tools.
- Dollar-based fractional orders are constrained by market session and broker
  eligibility rules.
- Cash-account settlement means sale proceeds are not immediately reusable for
  new stock buys.

## Order-Type Implications

Robinhood supports equity market, limit, stop, stop-limit, and trailing stop
orders. Robinhood support says bracket orders, market-on-close, and
market-on-open are not currently supported.

For this strategy:

- Whole-share target exits can often be represented by broker-native limit
  orders.
- Fractional `$1` positions may require active monitoring plus sell order review
  rather than relying entirely on broker-side target orders.
- Fractional market orders should be treated as regular-hours-only unless live
  tool review says otherwise.

## Useful References

- Fractional shares: https://robinhood.com/support/articles/66zKxGmw7zjdkFXEcGYksl/fractional-shares/
- Order types: https://robinhood.com/us/en/support/articles/order-types/
- Extended-hours trading: https://robinhood.com/us/en/support/articles/extendedhours-trading/
- Settlement and buying power: https://robinhood.com/us/en/support/articles/360001226946/

