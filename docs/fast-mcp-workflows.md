# Fast Robinhood MCP Workflows

The fast MCP scripts keep one authenticated Robinhood Agentic MCP session open
and make repeated read-only tool calls from Node. This avoids slow chat/tool
round trips for broad scans.

These scripts are for speed scanning and planning. They do not place orders.
Real sell and double-down execution still follows the broker review/place
workflow one candidate at a time.

## Safety Boundary

- Read-only bulk operations are allowed after the user asks for a fast check or
  explicitly approves bulk validation.
- Do not add bulk order placement to these scripts.
- Do not place real orders in parallel.
- When a sell or double-down candidate is found, stop the broad scan, refresh
  that symbol, run broker review if required, and place only that one order if
  the broker workflow allows it.
- Write outputs under ignored `data/runtime/` unless the user explicitly asks
  for post-market persistence.
- The scripts require `RH_ACCOUNT_NUMBER`; do not commit full account numbers.

## Shared Client

`scripts/rh_fast_mcp_client.mjs` contains the reusable MCP client:

- initializes one Robinhood MCP session
- calls MCP tools through `tools/call`
- handles event-stream and JSON responses
- supports paginated read calls
- includes small CSV/JSON helpers for runtime outputs

## Commands

Use the bundled Node runtime or any modern Node version.

```powershell
$env:RH_ACCOUNT_NUMBER = "<agentic account number>"
```

### FAST QUOTES

Bulk quote symbols without writing private state:

```powershell
node scripts/rh_fast.mjs quotes AAPL MSFT NVDA --output data/runtime/rh-fast-quotes.json
```

Use `--file` for a CSV that has a `symbol` column:

```powershell
node scripts/rh_fast.mjs quotes --file data/runtime/watchlist.csv
```

### FAST ORDERS

Fetch active equity orders quickly:

```powershell
node scripts/rh_fast.mjs orders --account $env:RH_ACCOUNT_NUMBER
```

Fetch one state:

```powershell
node scripts/rh_fast.mjs orders --account $env:RH_ACCOUNT_NUMBER --state queued
```

Fetch newest orders without active-state filtering:

```powershell
node scripts/rh_fast.mjs orders --account $env:RH_ACCOUNT_NUMBER --all
```

### FAST POSITIONS

Fetch positions, optionally with quote-based return estimates:

```powershell
node scripts/rh_fast.mjs positions --account $env:RH_ACCOUNT_NUMBER --with-quotes
```

Default outputs:

- `data/runtime/rh-fast-positions.json`
- `data/runtime/rh-fast-positions-summary.csv`

### FAST OPEN PLAN

Compare live positions and active orders against `data/universe.csv` and produce
eligible opening candidates. This uses live Robinhood broker state, not the
local ledger.

```powershell
node scripts/rh_fast.mjs open-plan --account $env:RH_ACCOUNT_NUMBER --limit 100
```

Default output:

- `data/runtime/rh-fast-open-plan.csv`

### FAST WATCH

Find rough sell/DD watch candidates from live positions and bulk quotes:

```powershell
node scripts/rh_fast.mjs watch --account $env:RH_ACCOUNT_NUMBER --mode both
```

Default output:

- `data/runtime/rh-fast-watch.json`

Important: `FAST WATCH` is a speed screen. It estimates returns from broker
position average price and bid/last quotes. Before any order, confirm the
strategy calculation with broker data, exact fills/lot state where required,
and the active review/place tool workflow.

### FAST UNIVERSE

Validate candidate symbols for universe expansion:

```powershell
$env:RH_VALIDATION_NEEDED = "1518"
node scripts/bulk_validate_robinhood_universe.mjs
```

Default outputs:

- `data/runtime/universe-expansion.validations.csv`
- `data/runtime/universe-expansion.rejections.csv`
