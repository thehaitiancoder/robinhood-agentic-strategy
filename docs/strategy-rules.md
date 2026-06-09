# Strategy Rules

## Objective

Own a very broad set of small Robinhood-tradable stock positions, sell complete
positions when the combined return reaches 10%, and add to losing positions
according to a predefined ladder without exhausting the cash needed to keep the
system alive.

## Universe

The desired universe is every eligible stock available on Robinhood. In
practice, production code must restrict this to symbols that are active,
tradable in the account, and eligible for the intended order style.

The current agent tools may not provide a complete Robinhood universe endpoint,
so the project needs a durable universe source. Every symbol from that source
must still pass Robinhood tradability checks before orders are considered.

## Position Lifecycle

- `candidate`: symbol is in the universe but not yet opened.
- `open`: symbol has an active position.
- `due_double_down`: current price has reached the next ladder trigger.
- `sell_ready`: combined position return is at least 10%.
- `closed_profit`: position was sold at or above target profit.
- `closed_emergency`: position was sold green below target to fund a higher
  priority double-down.
- `blocked`: symbol cannot be traded because of rule, broker, or data issues.

## Opening and Reopening Positions

Start new positions at the current global base amount. The first base is `$1`.
After the account has opened every eligible symbol at that base, the new-position
base increases by `$1`, then continues to `$3`, `$4`, and so on.

Open or reopen only when:

- No owned stock is due for double-down.
- The 10% cash buffer remains intact after the order.
- The position would remain below 10% of portfolio value.
- The symbol is active, tradable, and eligible for the intended order.
- The start-price cap is satisfied once that rule is confirmed.

## Profit Sell Rule

Sell the full combined position whenever the position reaches 10% profit.

Preferred calculation for sell candidates:

```text
return_pct = ((bid_price * quantity) - invested_cost) / invested_cost
```

Use bid-side pricing for sell decisions when available. Last trade can overstate
the executable return for thin or volatile names.

## Double-Down Rule

Each new lot doubles the prior lot's share count. For a `$1` initial lot at an
entry price of `P`, the first lot share count is:

```text
lot_1_shares = 1.00 / P
```

The next lot buys:

```text
lot_n_shares = lot_(n-1)_shares * 2
```

The trigger price uses the spreadsheet-style drop zones:

| Next lot range | Drop from previous trigger |
| --- | ---: |
| 2-5 | 10% |
| 6-10 | 20% |
| 11-15 | 40% |
| 16 | 80% |

The exact ranges should be validated against the original spreadsheet before
production code hard-codes them.

## Cash Priority

Disposable cash is not simply buying power. It must account for the cash buffer
and known double-down obligations.

```text
cash_floor = portfolio_value * 0.10
disposable_cash = buying_power - cash_floor
```

If any double-down is due, disposable cash is reserved for double-downs first.
New positions are paused.

## Emergency Cash Mode

If a double-down is due and there is not enough disposable cash:

1. Pause all new opens and reopens.
2. Identify positions with positive return below 10%.
3. Sell green positions as needed to create cash for the due double-down.
4. In a cash account, wait for settlement before treating sale proceeds as
   spendable.

## Concentration Cap

No single position may exceed 10% of portfolio value. For proposed buys:

```text
post_trade_position_value <= post_trade_portfolio_value * 0.10
```

If this rule blocks a double-down, the system must log the block and ask for
human review. It must not override the cap silently.

