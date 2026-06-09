# Implementation Roadmap

## Phase 0: Documentation and Repo Setup

Status: complete.

- Capture the strategy rules.
- Capture risk controls and operational priorities.
- Create a first config draft.
- Identify unresolved decisions.

## Phase 1: Read-Only Monitor

Status: started.

The repo now includes a local read-only monitor that:

- Pulls portfolio, position, quote, and universe data from snapshot files.
- Converts saved Robinhood tool payloads into monitor-ready snapshots.
- Calculates sell-ready positions.
- Calculates due double-downs.
- Blocks new openings when any double-down is due.
- Surfaces green emergency-sell candidates.
- Applies the cash buffer and concentration cap.
- Produces a JSON report without placing orders.

Remaining work:

- Add quote staleness thresholds.
- Add persistent position ledger reconstruction from fills.
- Add broader tests against spreadsheet-derived examples.

Success criteria:

- Calculations match hand checks.
- The ledger can be rebuilt from broker state and local fills.
- The system can explain every candidate and every skipped action.

## Phase 2: Paper or Simulated Execution

Run the full decision loop without live orders:

- Simulate fills from quote data.
- Track cash buffer and settlement.
- Stress test broad-universe scanning.
- Confirm that sell monitoring gets priority over buy scanning.

Success criteria:

- No rule violations in simulation.
- Emergency cash mode behaves predictably.
- Missing/stale quote data blocks new risk.

## Phase 3: Tiny Live Pilot

Use the Agentic account with `$1` base positions:

- Start with a small approved symbol subset.
- Use market execution for all strategy actions.
- Validate dollar-based fractional sizing for stocks at or above `$1.00`.
- Validate whole-share quantity sizing for sub-dollar stocks.
- Obey any runtime broker/tool confirmation requirements.
- Compare broker fills against the local order ledger and later position ledger.
- Validate fractional order behavior.

Success criteria:

- Orders reconcile cleanly.
- Sell-ready detection is fast enough.
- Double-down triggers match the spreadsheet rules.

## Phase 4: Universe Expansion

Expand symbol coverage in batches:

- Add more eligible symbols.
- Monitor quote and order throughput.
- Tune batching and stale-data thresholds.
- Keep runtime confirmation, when required by tooling, and audit logs intact.

## Phase 5: Production Controls

Before larger base sizes:

- Add persistent SQLite ledger.
- Add automatic daily reports.
- Add circuit breakers.
- Add test coverage for every hard rule.
- Add replay tests from historical quote/fill snapshots.
