from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_SYMBOL_POLICY_CSV = Path("data/symbol-policy.csv")

POLICY_FIELDS = [
    "symbol",
    "policy",
    "allow_open",
    "allow_reopen",
    "allow_double_down",
    "allow_sell",
    "reason",
    "evidence_source",
    "review_after",
    "updated_at",
]


@dataclass(frozen=True)
class SymbolPolicy:
    symbol: str
    policy: str = "eligible"
    allow_open: bool = True
    allow_reopen: bool = True
    allow_double_down: bool = True
    allow_sell: bool = True
    reason: str = ""
    evidence_source: str = ""
    review_after: str = ""
    updated_at: str = ""


def read_symbol_policy_csv(path: str | Path | None = DEFAULT_SYMBOL_POLICY_CSV) -> dict[str, SymbolPolicy]:
    if path is None:
        return {}
    csv_path = Path(path)
    if not csv_path.exists():
        return {}

    policies: dict[str, SymbolPolicy] = {}
    with csv_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            policy = _policy_from_row(row)
            if policy.symbol:
                policies[policy.symbol] = policy
    return policies


def write_symbol_policy_csv(path: str | Path, policies: Iterable[SymbolPolicy]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POLICY_FIELDS, lineterminator="\n")
        writer.writeheader()
        for policy in sorted(policies, key=lambda item: item.symbol):
            writer.writerow(_row_from_policy(policy))


def policy_for_symbol(
    symbol: str,
    policies: Mapping[str, SymbolPolicy] | None,
) -> SymbolPolicy:
    normalized = _normalize_symbol(symbol)
    if not policies:
        return SymbolPolicy(symbol=normalized)
    return policies.get(normalized, SymbolPolicy(symbol=normalized))


def is_open_allowed(symbol: str, policies: Mapping[str, SymbolPolicy] | None) -> bool:
    return policy_for_symbol(symbol, policies).allow_open


def is_reopen_allowed(symbol: str, policies: Mapping[str, SymbolPolicy] | None) -> bool:
    return policy_for_symbol(symbol, policies).allow_reopen


def is_double_down_allowed(symbol: str, policies: Mapping[str, SymbolPolicy] | None) -> bool:
    return policy_for_symbol(symbol, policies).allow_double_down


def is_sell_allowed(symbol: str, policies: Mapping[str, SymbolPolicy] | None) -> bool:
    return policy_for_symbol(symbol, policies).allow_sell


def _policy_from_row(row: dict[str, str]) -> SymbolPolicy:
    return SymbolPolicy(
        symbol=_normalize_symbol(row.get("symbol", "")),
        policy=_text(row.get("policy")) or "eligible",
        allow_open=_bool(row.get("allow_open"), default=True),
        allow_reopen=_bool(row.get("allow_reopen"), default=True),
        allow_double_down=_bool(row.get("allow_double_down"), default=True),
        allow_sell=_bool(row.get("allow_sell"), default=True),
        reason=_text(row.get("reason")),
        evidence_source=_text(row.get("evidence_source")),
        review_after=_text(row.get("review_after")),
        updated_at=_text(row.get("updated_at")),
    )


def _row_from_policy(policy: SymbolPolicy) -> dict[str, str]:
    return {
        "symbol": policy.symbol,
        "policy": policy.policy,
        "allow_open": _bool_text(policy.allow_open),
        "allow_reopen": _bool_text(policy.allow_reopen),
        "allow_double_down": _bool_text(policy.allow_double_down),
        "allow_sell": _bool_text(policy.allow_sell),
        "reason": policy.reason,
        "evidence_source": policy.evidence_source,
        "review_after": policy.review_after,
        "updated_at": policy.updated_at,
    }


def _normalize_symbol(symbol: str) -> str:
    return _text(symbol).upper()


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bool(value: object, *, default: bool) -> bool:
    text = _text(value).lower()
    if text == "":
        return default
    return text in {"1", "true", "yes", "y"}


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or inspect a symbol policy CSV.")
    parser.add_argument("--validate", default=str(DEFAULT_SYMBOL_POLICY_CSV), help="Policy CSV to validate.")
    args = parser.parse_args()

    policies = read_symbol_policy_csv(args.validate)
    print(f"policy_rows={len(policies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
