# Robinhood Agentic Strategy

This repository documents and will eventually implement the user's Robinhood
agentic trading strategy. The immediate purpose is to preserve the rules clearly
enough that future agents can continue without reinterpreting the strategy from
chat history.

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

## Hard Guardrails

- Keep at least 10% of portfolio value as cash buffer.
- Do not open or reopen positions while any owned symbol is due for a
  double-down.
- Do not allow one position to exceed 10% of portfolio value.
- Sell the full combined position when it reaches 10% profit.
- If cash is short and a double-down is due, sell green positions below 10%
  profit before opening anything new.
- Do not place real orders without following the active broker/tool
  confirmation requirements.
- Keep a complete audit trail of every candidate, skipped action, review, order,
  fill, and rule block.

## Repository Map

- `AGENTS.md`: required reading for future agents.
- `docs/strategy-rules.md`: strategy rules in plain English.
- `docs/operating-model.md`: daily and intraday operating flow.
- `docs/data-model.md`: entities, fields, and calculations.
- `docs/risk-controls.md`: hard blocks, warnings, and circuit breakers.
- `docs/robinhood-tooling.md`: current Robinhood tool capabilities and gaps.
- `docs/implementation-roadmap.md`: phased build plan.
- `docs/open-questions.md`: decisions that must be confirmed before production.
- `config/strategy.example.yaml`: first machine-readable rules draft.
- `data/README.md`: where future universe, fills, and ledger data should live.

## Source References

Useful Robinhood support references:

- Fractional shares: https://robinhood.com/support/articles/66zKxGmw7zjdkFXEcGYksl/fractional-shares/
- Order types: https://robinhood.com/us/en/support/articles/order-types/
- Extended-hours trading: https://robinhood.com/us/en/support/articles/extendedhours-trading/
- Settlement and buying power: https://robinhood.com/us/en/support/articles/360001226946/

