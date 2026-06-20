# Pending Reopen Queue

`data/private/sold-today.md` is the ignored durable queue of symbols sold for
profit and not yet reopened as tracking lots. The filename is legacy
compatibility; the file is no longer limited to the current day and must not be
cleared just because a new Pacific trading day begins.

It is not sell history and it is not an ownership source of truth. Before
reopening any symbol from this file, refresh Robinhood positions, active
orders, buying power, double-down obligations, tradability, fractional
eligibility, and symbol policy.

## Format

Keep the file simple:

```text
# Pending Reopen Queue
Updated: 2026-06-18 PT

| Sold Date | Sold Time | Symbol | Sell Order ID | Reason Reopen Blocked | Attempt Count | Last Attempt At |
| --- | --- | --- | --- | --- | ---: | --- |
| 2026-06-15 | 08:29 PT | UCTT | 6a... | cash_buffer | 0 |  |
```

One pending reopen per row. Use the sell fill date/time when known; otherwise
use the time the sell order is confirmed filled. If that symbol is later
reopened and the reopen buy is confirmed filled, remove it from this file.
Prices, quantities, return calculations, and complete broker payloads still
belong in broker history or the optional audit ledger.

## When To Write

During market hours, sell and double-down execution speed comes first. Do not
write this file while an executable sell or double-down candidate is waiting.

After the sell workflow is done for the current run:

1. Confirm each sell order reached `filled` state in Robinhood.
2. If a market-hours automation immediately reopens the sold symbol as a base
   tracking lot and the reopen buy is confirmed filled, do not append that
   symbol as pending.
3. Append only the filled sell symbols that still need reopen and are allowed
   to reopen by policy to `data/private/sold-today.md` as pending reopens.
4. Then continue with any non-urgent cleanup such as shortlist updates.

If a run places multiple sells, append them together after the sell execution
batch is complete. If a later run sells another symbol, append that symbol after
that run's sell workflow is complete.

After a reopen workflow is done:

1. Confirm each reopen buy reached `filled` state in Robinhood.
2. Remove those reopened symbols from `data/private/sold-today.md`.

## No Daily Reset

Do not clear this queue at the beginning of a new Pacific trading day. Pending
reopen obligations can span multiple days. The helper keeps the old `--reset`
flag for compatibility with older automation prompts, but it now only
initializes or re-renders the file and preserves every existing pending entry.

```powershell
$env:PYTHONPATH = "src"
python -m agentic_strategy.sold_today --reset
```

Append symbols after confirmed sell fills:

```powershell
$env:PYTHONPATH = "src"
python -m agentic_strategy.sold_today --symbol CBRL --symbol TGTX
```

Remove symbols after confirmed reopen fills:

```powershell
$env:PYTHONPATH = "src"
python -m agentic_strategy.sold_today --reopened-symbol CBRL --reopened-symbol TGTX
```

If recording a known fill timestamp:

```powershell
$env:PYTHONPATH = "src"
python -m agentic_strategy.sold_today --symbol UCTT --sold-at 2026-06-10T14:29:06Z
```

## Reopening Rule

`REOPEN SOLD` means:

1. Read `data/private/sold-today.md`.
2. Refresh Robinhood broker state.
3. Skip symbols already held or already covered by active buy orders.
4. Run the strategy priority checks first: sell targets, due double-downs,
   emergency cash need, 15% cash buffer, symbol policy, and concentration cap.
5. Reopen eligible symbols as base lots only if disposable cash remains.

If policy blocks the reopen, do not keep the symbol in the sold-today queue. If
cash is needed for double-downs or the 15% buffer, leave the symbol in the
sold-today pending reopen queue for later user-directed reopening.

The market-hours automation has one standing exception to the user-directed
reopen flow: after a profitable sell fills, it may immediately reopen that same
symbol as a base tracking lot without waiting for user confirmation when the
fast blockers pass and symbol policy permits reopen. It should not run a broad
DD scan before that tracking reopen.
