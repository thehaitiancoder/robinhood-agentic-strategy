from __future__ import annotations

import argparse

from .engine import evaluate_strategy
from .io import (
    load_config_json,
    load_portfolio_json,
    load_positions_csv,
    load_quotes_csv,
    load_universe_csv,
    report_to_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the read-only strategy monitor.")
    parser.add_argument("--portfolio", required=True, help="Path to portfolio JSON snapshot.")
    parser.add_argument("--positions", required=True, help="Path to positions CSV snapshot.")
    parser.add_argument("--quotes", required=True, help="Path to quotes CSV snapshot.")
    parser.add_argument("--universe", required=True, help="Path to universe CSV snapshot.")
    parser.add_argument("--config-json", help="Optional JSON strategy config override.")
    args = parser.parse_args()

    report = evaluate_strategy(
        portfolio=load_portfolio_json(args.portfolio),
        positions=load_positions_csv(args.positions),
        quotes=load_quotes_csv(args.quotes),
        universe=load_universe_csv(args.universe),
        config=load_config_json(args.config_json),
    )
    print(report_to_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

