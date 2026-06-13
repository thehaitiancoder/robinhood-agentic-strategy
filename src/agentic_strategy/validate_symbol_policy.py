from __future__ import annotations

import argparse

from .symbol_policy import DEFAULT_SYMBOL_POLICY_CSV, read_symbol_policy_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a symbol policy CSV.")
    parser.add_argument("--policy", default=str(DEFAULT_SYMBOL_POLICY_CSV), help="Policy CSV to validate.")
    args = parser.parse_args()

    policies = read_symbol_policy_csv(args.policy)
    print(f"policy_rows={len(policies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
