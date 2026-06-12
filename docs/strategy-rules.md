# Strategy Rules

## Objective

Own a very broad set of small Robinhood-tradable stock positions, sell complete
positions when the combined return reaches 10%, and add to losing positions
according to a predefined ladder without exhausting the cash needed to keep the
system alive.

## Universe

The desired universe is every eligible stock available on Robinhood. The
canonical universe is the local `data/universe.csv` file, built incrementally
from user-supplied candidate symbols after Robinhood tradability validation.

Production code must restrict openings to symbols that are active, tradable in
the account, and eligible for the intended order style. Delisted, inactive, or
non-tradable symbols should be marked inactive/non-tradable in the universe
instead of deleted silently.

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
- The symbol is not halted, paused, frozen, or otherwise blocked from current
  order execution.

There is no share-price cap for opening positions. A high-priced stock can still
be opened with a `$1` fractional order if the account has deployable cash and
the symbol is eligible.

Opening size depends on share price:

- Stocks priced at `$1.00` or higher use dollar-based fractional sizing.
- Stocks priced below `$1.00` use whole-share quantity sizing. Do not buy
  fractional shares for sub-dollar penny stocks.
- For sub-dollar stocks, choose the whole-share quantity that fits within the
  target lot dollars, with a minimum of 1 whole share.

There is also no wash-sale or tax cooldown for openings or reopenings. Strategy
decisions use actual fill prices and actual dollars invested, not tax-adjusted
broker cost basis.

## Sold-Today Reopen Queue

When a profit sell fills, add the symbol to `data/private/sold-today.md` after
the sell execution workflow is complete if the symbol has not been reopened.
This file is reset at the beginning of each Pacific trading day and contains
only sell time plus symbol.

Market-hours automation exception: after a qualifying profitable sell order is
confirmed filled, immediately reopen that same symbol as a base tracking lot if
the fast blockers pass. This keeps a live marker on strong intraday runners and
lets the strategy capture repeated sell cycles. Do not run a broad DD scan
between the sell fill and this tracking reopen; only check current buying power
and 10% cash buffer, known due or cash-short DDs from this run, active buy
orders for the same symbol, halted/restricted broker state, and normal base-lot
sizing. If the immediate reopen fills, do not keep the symbol in
`sold-today.md`; if the reopen is blocked, leave or add it there for later.

The sold-today list exists so the user can later reopen recently closed symbols
before buying unrelated new names. It should contain only symbols sold today
that are still not reopened. When a reopen buy is confirmed filled, remove that
symbol from the list. It is not a trading authority. `REOPEN SOLD` must refresh
Robinhood first, skip symbols already held or covered by active buy orders,
then apply the normal priority checks:

- sell targets first
- due double-downs before reopens
- emergency cash needs before reopens
- 10% cash buffer
- 10% single-position cap
- active, tradable, eligible symbol

If cash is needed for double-downs or the buffer, leave the symbol in the
sold-today pending reopen list for later user-directed reopening.

## Profit Sell Rule

Sell the full combined position whenever the position reaches 10% profit.

Preferred calculation for sell candidates:

```text
return_pct = ((bid_price * quantity) - invested_cost) / invested_cost
```

Use bid-side pricing for sell decisions when available. Last trade can overstate
the executable return for thin or volatile names.

## Manual Sell-Auto Trigger

`SELL AUTO UNTIL CLOSE`, abbreviated `SAUCE`, is a manual chat trigger for an
active sell-only loop. It is pre-authorized to place qualifying full-position
10% profit sells after a clean broker review without asking the user for another
confirmation.

When the user invokes `SAUCE` during regular market hours:

1. Scan current live broker positions and quotes for sell targets.
2. For each candidate, refresh/review the sell through the broker workflow.
3. If the broker review is clean, the symbol is not halted or restricted, the
   full sellable quantity is available, and bid-side return is still at least
   10%, place the full-position market sell immediately.
4. Resume scanning for the next candidate.
5. Continue until 12:59 PM Pacific, then stop before the regular market close.

`SAUCE` authorizes sells only. It does not authorize double-downs, openings,
reopens, emergency green sells, or after-hours orders. Do not delay a qualifying
sell for local ledger, shortlist, or sold-today writes.

## Execution And Sizing Rule

Strategy orders use immediate market execution when criteria are met. This
applies to openings, reopenings, double-downs, target sells, and emergency green
sells.

Do not place market orders while a symbol is halted, paused for volatility,
frozen, or not accepting orders. Treat the displayed halt price as stale. After
trading resumes, refresh Robinhood quote/order state and re-run the normal
sell/DD/opening checks from live broker data.

Do not use GTC limit orders or broker-native persistent target exits as the
strategy design. The execution system should monitor rules and execute market
orders when criteria are met. The user does not want manual order monitoring.

Do not interpret market execution to mean every buy is dollar-based fractional.
Openings and reopenings priced at `$1.00` or higher use dollar-based fractional
order sizing; sub-dollar penny stocks use whole-share quantity order sizing.
Double-down buys are different: they must use exact share quantity sizing from
the lot ladder.

If the active broker or agent tool requires review or explicit confirmation for
real-money order placement, implementation must obey that runtime constraint
while preserving the strategy goal of automatic execution when compliant tooling
allows it.

## Double-Down Rule

Each new lot doubles the prior lot's share count. For a `$1` initial lot at an
entry price of `P >= $1.00`, the first lot share count is:

```text
lot_1_shares = 1.00 / P
```

For a sub-dollar stock, the first lot is a whole-share quantity that fits within
the target lot dollars:

```text
lot_1_shares = floor(1.00 / P), minimum 1 share
```

The next lot buys:

```text
lot_n_shares = lot_(n-1)_shares * 2
```

Double-down broker orders must be reviewed and placed with `quantity` equal to
`lot_n_shares`. Do not submit a DD as a rounded `dollar_amount`, even when the
stock is priced at or above `$1.00`; use the estimated dollar value only to
check actual buying power and concentration risk.

During live market checks, a full basket scan is preferred. If the monitor
cannot exhaustively scan every live position, it must still validate the top
downside holdings directly before reporting that no double-down is due. Any
owned symbol exposed by the downside shortlist, a partial broker/fast scan, or
other current broker-backed evidence at `<= -10%` return and with no active buy
order is a mandatory DD verification candidate.

That `<= -10%` screen is not automatic buy authority. For each candidate, fetch
the filled buy/order history needed to reconstruct current lot state, calculate
the exact `next_lot_shares` and `next_trigger_price`, refresh the live quote,
and buy only if current ask price is at or below the next trigger and cash,
buffer, concentration, and broker checks pass. Do not stop after checking only
symbols that already doubled down recently.

If the monitor cannot exhaustively scan the basket and cannot verify those
mandatory downside candidates, it must not call the result "no DD due." The
correct status is `DD SCAN BLOCKED` with the exact missing coverage or tool
failure. During market-hours automations, that blocked scan must email the user
because a due double-down may be waiting.

The trigger price uses the spreadsheet-style drop zones. Lot 1 is the base open:

| Lot range | Drop from previous trigger | Number of buys |
| --- | ---: | ---: |
| 1 | 0% | base open |
| 2-5 | 10% | 4 |
| 6-10 | 20% | 5 |
| 11-15 | 40% | 5 |
| 16+ | 80% | 5-buy zones, repeated |

The 80% zone can continue indefinitely in theory. In practice, the sequence
should stop when the stock is sold, delisted, blocked by the 10% position cap,
or cash rules prevent another double-down.

## Cash Priority

For openings and reopens, disposable cash is not simply buying power. It must
account for the cash buffer and known double-down obligations.

```text
cash_floor = portfolio_value * 0.10
disposable_cash = buying_power - cash_floor
```

The cash floor is a reserve for double-downs. It blocks new openings, sold-symbol
reopens, and post-sell tracking reopens, but it must not block a due DD merely
because executing the DD would move buying power below the floor. For DD
affordability, use actual broker buying power plus concentration and broker
review checks. If any double-down is due, new positions are paused.

## Emergency Cash Mode

If a double-down is due and there is not enough actual broker buying power:

1. Pause all new opens and reopens.
2. Identify positions with positive return below 10%.
3. Rank those green positions by highest positive return first.
4. Sell green positions as needed to create cash for the due double-down.
5. In a cash account, wait for settlement before treating sale proceeds as
   spendable.

## Concentration Cap

No single position may exceed 10% of portfolio value. For proposed buys:

```text
post_trade_position_value <= post_trade_portfolio_value * 0.10
```

If this rule blocks a double-down, the system must log the block and ask for
human review. It must not override the cap silently.
