# Data Model

This model should be implemented in a durable store before scaling past small
live tests. SQLite is enough for the first implementation.

## Symbol

| Field | Meaning |
| --- | --- |
| `symbol` | Ticker |
| `name` | Company or fund name |
| `asset_type` | Stock, ETF, etc. |
| `tradable` | Broker says account can trade it |
| `fractional_eligible` | Eligible for dollar-based fractional orders |
| `active` | Not halted, delisted, or otherwise inactive |
| `source` | Universe provider |
| `updated_at` | Last validation time |

Sub-dollar stocks do not need fractional eligibility for the strategy's opening
logic because they use whole-share quantity sizing instead of dollar-based
fractional sizing.

The canonical universe source is local `data/universe.csv`, populated from
Robinhood validation results. Delisted, inactive, or non-tradable symbols remain
in the file with `active=false` or `tradable=false` for auditability.

## Position

| Field | Meaning |
| --- | --- |
| `symbol` | Ticker |
| `quantity` | Current shares |
| `invested_cost` | Actual dollars invested from fills, not tax-adjusted wash-sale basis |
| `average_cost` | Strategy average cost |
| `market_value` | Current estimated value |
| `return_pct` | Combined return |
| `state` | Position lifecycle state |
| `current_lot_index` | Highest lot reached |
| `next_lot_shares` | Shares required for next double-down |
| `next_trigger_price` | Price that triggers next double-down from the ladder |
| `target_sell_price` | Combined price needed for 10% return |

## Lot

| Field | Meaning |
| --- | --- |
| `symbol` | Ticker |
| `lot_index` | 1 for initial lot, increasing after each add |
| `shares` | Shares bought in this lot |
| `trigger_price` | Ladder trigger price for this lot |
| `sizing_mode` | `dollar_fractional` or `whole_share_quantity` |
| `fill_price` | Actual average fill price |
| `cost` | Filled dollars |
| `order_id` | Broker order id |
| `filled_at` | Fill timestamp |

## Tax Handling

The strategy does not use wash-sale rules or tax-adjusted cost basis for trade
decisions. Store actual fills and realized gain/loss for audit purposes, but do
not apply a 31-day wash-sale cooldown and do not block openings, reopenings,
double-downs, or target sells for tax reasons.

## Decision Log

Every loop should write a decision record whether or not an order is placed.

| Field | Meaning |
| --- | --- |
| `timestamp` | Decision time |
| `symbol` | Ticker, if applicable |
| `decision_type` | sell, double_down, open, reopen, emergency_sell, block |
| `inputs` | Quote, cash, position, and rule inputs |
| `decision` | Proposed action or block |
| `reason` | Human-readable reason |
| `order_id` | Broker order id, if placed |
| `agent_run_id` | Agent or job identifier |

## Calculations

Sell return:

```text
return_pct = ((bid_price * quantity) - invested_cost) / invested_cost
```

Target sell price:

```text
target_sell_price = (invested_cost * 1.10) / quantity
```

Cash floor:

```text
cash_floor = portfolio_value * 0.10
```

Position concentration:

```text
position_pct = position_market_value / portfolio_value
```
