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

- Strategy stock orders should use immediate market execution when criteria are
  met.
- Do not use broker-native GTC limit target exits as the strategy design.
- The execution system should monitor criteria and submit market orders when a
  target sell, emergency green sell, double-down, open, or reopen condition is
  met.
- Openings and reopenings at or above `$1.00` use dollar-based fractional
  sizing when eligible.
- Sub-dollar penny stocks use whole-share quantity sizing and should not be
  bought fractionally.
- Double-down buys must be submitted with share `quantity`, not with a rounded
  `dollar_amount`. When multiple same-symbol DD lots are due, combine the due
  lot shares into one order. If Robinhood rejects the fractional DD quantity,
  retry the integer part only when it is at least 1 share.
- Fractional market orders should be treated as regular-hours-only unless live
  tool review says otherwise. Whole-share sub-dollar orders still need live
  tradability and broker review/response handling.
- If current live tools require order review or explicit confirmation, obey that
  as a runtime tooling constraint.

## Useful References

- Fractional shares: https://robinhood.com/support/articles/66zKxGmw7zjdkFXEcGYksl/fractional-shares/
- Order types: https://robinhood.com/us/en/support/articles/order-types/
- Extended-hours trading: https://robinhood.com/us/en/support/articles/extendedhours-trading/
- Settlement and buying power: https://robinhood.com/us/en/support/articles/360001226946/
