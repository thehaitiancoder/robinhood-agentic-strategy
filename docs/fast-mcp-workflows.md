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
- If a broad position/watch scan cannot complete or returns truncated coverage,
  still verify the top downside holdings directly before reporting no DD due.
  Any owned symbol surfaced at `<= -10%` return with no active buy order is a
  mandatory DD verification candidate: fetch filled buys/orders, reconstruct
  all same-symbol due lots, refresh the quote, and compare current ask to the
  deepest included trigger.
- If the fast path is blocked and no other path can verify the mandatory
  downside candidates, the correct result is `DD SCAN BLOCKED`; do not emit a
  routine no-action report.
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

### FAST PORTFOLIO

Fetch the Agentic account portfolio snapshot without writing private state:

```powershell
node scripts/rh_fast.mjs portfolio --account $env:RH_ACCOUNT_NUMBER --output data/runtime/rh-fast-portfolio.json
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
local ledger. It also applies `data/symbol-policy.csv` by default when the file
exists.

```powershell
node scripts/rh_fast.mjs open-plan --account $env:RH_ACCOUNT_NUMBER --limit 100
```

Use `--symbol-policy <path>` to point at a different policy file.

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

If `FAST WATCH` or the underlying broker payloads cannot cover the full live
position basket, treat its worst downside symbols plus the committed top-buy
shortlist as mandatory DD verification input. Do not conclude "no DD due" from
only checking positions that already had recent DD activity.

### FAST UNIVERSE

Validate candidate symbols for universe expansion:

```powershell
$env:RH_VALIDATION_NEEDED = "1518"
node scripts/bulk_validate_robinhood_universe.mjs
```

Default outputs:

- `data/runtime/universe-expansion.validations.csv`
- `data/runtime/universe-expansion.rejections.csv`

### MONTHLY UNIVERSE DISCOVERY

Fetch current Nasdaq Trader symbol directories, build common-stock candidates
not already in `data/universe.csv`, validate them through Robinhood
tradability, and merge only active/tradable/fractional results:

```powershell
node scripts/monthly_universe_discovery.mjs --run --account $env:RH_ACCOUNT_NUMBER
```

For a no-merge candidate smoke test:

```powershell
node scripts/monthly_universe_discovery.mjs --dry-run --candidate-limit 25
```

Default outputs:

- `data/runtime/monthly-universe-discovery/<date>/candidates.csv`
- `data/runtime/monthly-universe-discovery/<date>/validations.csv`
- `data/runtime/monthly-universe-discovery/<date>/rejections.csv`
- `data/runtime/monthly-universe-discovery/<date>/summary.md`
