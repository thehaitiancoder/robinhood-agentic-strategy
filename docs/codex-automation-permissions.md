# Codex Automation Permissions

This repo has a committed Codex project layer for Robinhood strategy
automations:

- `.codex/config.toml`
- `.codex/rules/robinhood-automation.rules`

The project config keeps automations in `workspace-write`, turns on network
access for repo commands, and sets `PYTHONPATH=src` so Python helpers can run as
`python -m agentic_strategy.<module>` without shell-specific environment
assignment.

The rules file allows only the narrow command prefixes used by this project:

- `node scripts/rh_fast.mjs ...`
- `node scripts/bulk_validate_robinhood_universe.mjs`
- `node scripts/monthly_universe_discovery.mjs ...`
- `node scripts/weekly_symbol_policy_refresh.mjs ...`
- `python -m agentic_strategy.sold_today ...`
- `python -m agentic_strategy.shortlists ...`
- `python -m agentic_strategy.current_symbols ...`
- `python -m agentic_strategy.ledger ...`
- `python -m agentic_strategy.broker_snapshot ...`
- `python -m agentic_strategy.universe ...`
- `python -m agentic_strategy.validate_symbol_policy ...`
- `python -m agentic_strategy.afterhours_scan ...`
- `python -m agentic_strategy.daily_summary ...`

These rules are for command escalation outside the sandbox. They are not the
filesystem permission source. Repo-local write access comes from
`workspace-write` with the automation cwd set to the repo root.

## Files Covered

With the automation cwd set to the repo root, agents should be able to write
the strategy files that live inside the workspace:

- `data/private/sold-today.md`
- `data/private/order-ledger.csv`
- `data/private/current-symbols.json`
- `data/private/close-summary.md`
- `data/private/top-10-buy-candidates.md`
- `data/private/top-10-sell-candidates.md`
- `data/private/daily-summary.md`
- `data/private/daily-summary.json`
- `data/private/daily-return-cycles.csv`
- `data/private/performance-history.md`
- `data/private/performance-history.csv`
- `data/private/latest/*`
- `data/runtime/*`
- `data/universe.csv`
- `data/symbol-policy.csv`

Do not add the automation memory directory as a second cwd. In Codex
automations, multiple cwd entries launch multiple runnable workspaces and can
create duplicate threads.

## Activation

Codex loads project-local rules from `.codex/rules/` only when the project
`.codex/` layer is trusted. After changing config or rules, restart Codex or
start a fresh automation run so the scheduler loads the updated project layer.

If a future run still reports `Access to the path ... is denied` for a
repo-local file, check:

1. the automation `cwds` field is exactly the repo root;
2. the run loaded this repo's trusted `.codex/config.toml`;
3. the target path is under this repo, not under
   `C:\Users\ralph\.codex\automations\...`;
4. the command used one of the allowed narrow prefixes instead of a shell
   wrapper with environment assignments or redirection.

The automation `memory.md` file is outside this repo. It is intentionally not
covered here because market execution should not depend on writing automation
memory.
