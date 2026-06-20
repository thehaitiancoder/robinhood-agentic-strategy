# Robinhood Agentic Strategy

This repository documents and implements the user's Robinhood agentic trading
strategy. The immediate purpose is to preserve the rules clearly enough that
future agents can continue without reinterpreting the strategy from chat
history.

This is an execution and automation project, not a recommendation engine. The
strategy rules come from the user and must be treated as configuration and
operating constraints.

## Strategy Summary

The strategy starts with small fractional positions across a very broad
Robinhood-tradable stock universe. It sells complete positions when the combined
position reaches a 10% profit. It adds to losing positions according to a
predefined averaging-down ladder, while protecting cash and preventing any
single position from becoming too large.

The main failure mode to prevent is not a bad spreadsheet formula. It is
operational drift: too many symbols to scan manually, missed sell windows, lack
of filtering, insufficient reserved cash for required double-downs, and
overriding hard rules.

## Current Status

Phase 1 has started. The repo now includes a pure-Python read-only monitor that
evaluates portfolio, position, quote, and universe snapshots. It does not call
Robinhood and cannot place orders.

Run the example:

```bash
PYTHONPATH=src python3 -m agentic_strategy.monitor \
  --portfolio examples/portfolio.json \
  --positions examples/positions.csv \
  --quotes examples/quotes.csv \
  --universe examples/universe.csv \
  --config-json config/strategy.example.json \
  --symbol-policy data/symbol-policy.csv
```

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Hard Guardrails

- Keep at least 15% of portfolio value as cash buffer.
- Do not open or reopen positions while any owned symbol is due for a
  double-down.
- Do not allow one position to exceed 10% of portfolio value.
- Sell the full combined position when it reaches 10% profit.
- If cash is short and a double-down is due, sell green positions below 10%
  profit before opening anything new.
- Use market execution when criteria are met; size sub-dollar stocks in whole
  shares instead of fractional shares.
- Do not place real orders without following the active broker/tool
  confirmation requirements.
- Keep a complete audit trail of every candidate, skipped action, review, order,
  fill, and rule block.

## Repository Map

- `AGENTS.md`: required reading for future agents.
- `src/agentic_strategy/`: read-only strategy engine.
- `tests/`: unit tests for the hard rules.
- `examples/`: sample snapshots for local monitor runs.
- `docs/strategy-rules.md`: strategy rules in plain English.
- `docs/universe-management.md`: how to build and maintain the RH universe.
- `docs/symbol-policy.md`: durable open/reopen filters layered over the
  universe.
- `docs/live-snapshot-workflow.md`: how to convert live Robinhood tool outputs
  into monitor snapshots without committing private account data.
- `docs/monitor-usage.md`: how to run the read-only monitor.
- `docs/current-symbols.md`: post-market current-symbol cache and opening
  candidate selector.
- `docs/shortlists.md`: previous-run top-10 buy/sell watchlists for faster
  market checks.
- `docs/sold-today.md`: durable pending-reopen queue at the legacy
  `sold-today.md` path.
- `docs/fast-mcp-workflows.md`: read-only fast Robinhood MCP scripts for broad
  scans and planning.
- `docs/live-state.md`: deprecated legacy live-state handoff workflow.
- `docs/order-ledger.md`: how to persist local audit ledger events.
- `docs/shortcuts.md`: short commands the user can give future agents.
- `docs/automation-monitor.md`: Codex automation schedule, alerts, and writable roots.
- `scripts/weekly_symbol_policy_refresh.mjs`: weekend historical range refresh
  for generated symbol-policy rows, with Yahoo primary and Robinhood fallback.
- `docs/operating-model.md`: daily and intraday operating flow.
- `docs/data-model.md`: entities, fields, and calculations.
- `docs/risk-controls.md`: hard blocks, warnings, and circuit breakers.
- `docs/robinhood-tooling.md`: current Robinhood tool capabilities and gaps.
- `docs/implementation-roadmap.md`: phased build plan.
- `docs/decisions.md`: confirmed strategy decisions.
- `config/strategy.example.yaml`: first machine-readable rules draft.
- `config/strategy.example.json`: config used by the Python monitor.
- `data/README.md`: where universe, private caches, audit ledger, fills, and runtime data live.
- `scripts/`: local helper scripts, including read-only fast Robinhood MCP
  workflows.

## Source References

Useful Robinhood support references:

- Fractional shares: https://robinhood.com/support/articles/66zKxGmw7zjdkFXEcGYksl/fractional-shares/
- Order types: https://robinhood.com/us/en/support/articles/order-types/
- Extended-hours trading: https://robinhood.com/us/en/support/articles/extendedhours-trading/
- Settlement and buying power: https://robinhood.com/us/en/support/articles/360001226946/
