# Sold Today Pending Reopen

`data/private/sold-today.md` is a small ignored daily queue of symbols sold
during the current Pacific trading day and not yet reopened. It exists only so
the user can later ask an agent to reopen recently closed names instead of
finding unrelated new openings.

It is not sell history and it is not an ownership source of truth. Before
reopening any symbol from this file, refresh Robinhood positions, active
orders, buying power, double-down obligations, tradability, and fractional
eligibility.

## Format

Keep the file simple:

```text
# Sold Today Pending Reopen
Date: 2026-06-10 PT

08:29 PT UCTT
```

One pending reopen per line. Use the sell fill time when known; otherwise use
the time the sell order is confirmed filled. If that symbol is later reopened
and the reopen buy is confirmed filled, remove it from this file. Do not add
quantities, prices, return calculations, broker order ids, or notes here. Those
belong in broker history or the optional audit ledger.

## When To Write

During market hours, sell and double-down execution speed comes first. Do not
write this file while an executable sell or double-down candidate is waiting.

After the sell workflow is done for the current run:

1. Confirm each sell order reached `filled` state in Robinhood.
2. Append the filled sell symbols to `data/private/sold-today.md` as pending
   reopens.
3. Then continue with any non-urgent cleanup such as shortlist updates.

If a run places multiple sells, append them together after the sell execution
batch is complete. If a later run sells another symbol, append that symbol after
that run's sell workflow is complete.

After a reopen workflow is done:

1. Confirm each reopen buy reached `filled` state in Robinhood.
2. Remove those reopened symbols from `data/private/sold-today.md`.

## Daily Reset

At the beginning of each Pacific trading day, clear the list before market
checks begin. The helper command also resets automatically if the date in the
file is stale.

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
   emergency cash need, 10% cash buffer, and concentration cap.
5. Reopen eligible symbols as base lots only if disposable cash remains.

If cash is needed for double-downs or the 10% buffer, leave the symbol in the
sold-today pending reopen queue for later user-directed reopening.
