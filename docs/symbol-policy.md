# Symbol Policy

`data/symbol-policy.csv` is the committed strategy overlay for symbols that
should stay in the universe but should not be selected for future buying.

The universe remains broker-truth metadata. Do not delete a stock from
`data/universe.csv` just because the strategy no longer wants to buy it.
Use the policy file instead.

## Columns

- `symbol`: uppercase ticker.
- `policy`: human-readable policy name, such as `no_new_open`, `no_reopen`, or
  `exit_only`.
- `allow_open`: whether the strategy may open a new position.
- `allow_reopen`: whether the strategy may reopen a sold symbol.
- `allow_double_down`: whether owned-position DD checks remain allowed.
- `allow_sell`: whether sell checks remain allowed.
- `reason`: short rule explanation.
- `evidence_source`: source used to create or update the rule.
- `review_after`: optional future review date.
- `updated_at`: date the row was last updated.

Missing symbols default to fully eligible.

Manual rows may disable owned-position actions. If `allow_double_down=false`,
automation must skip DD checks for that symbol and must not count it as a DD
coverage blocker. If `allow_sell=false`, automation must leave sell handling to
the user.

## Current Filter

As of 2026-06-13, symbols with `valid_months = 6` and
`avg_monthly_range_pct < 10` in the six-month intraday range analysis are
filtered. Yahoo Finance is the primary historical source; if Yahoo fetching
fails for a symbol, Robinhood historical bars are used for that symbol.

- If currently owned, policy is `no_reopen`.
- If not currently owned, policy is `no_new_open`.
- Both policies set `allow_open=false` and `allow_reopen=false`.
- Both policies keep `allow_double_down=true` and `allow_sell=true`.

That implements a phased exit for owned non-movers: keep normal sell and DD
coverage while owned, but do not buy them back after they are sold.

The >100% swing filter is intentionally not active yet.

## Weekly Refresh

The Sunday automation `weekly-rh-symbol-policy-refresh` rebuilds only the
auto-managed part of this file from six months of monthly intraday high/low
data. It removes old auto-generated rows for symbols that become active movers
again and adds rows for newly slow symbols.

Historical range fetching is Yahoo-first. A Yahoo failure for one symbol should
fall back to Robinhood daily historical bars before the symbol is counted as a
failure.

Manual rows are preserved. A row is auto-managed only when its evidence source
starts with `weekly_intraday_range_` or `yahoo_intraday_range_`, its policy is
`no_new_open` or `no_reopen`, and its permissions match the generated phased
exit pattern:

- `allow_open=false`
- `allow_reopen=false`
- `allow_double_down=true`
- `allow_sell=true`

The weekly job writes metrics, diffs, backups, and summaries under
`data/runtime/`. It aborts without replacing this file if fewer than 95% of the
universe symbols are successfully analyzed.
