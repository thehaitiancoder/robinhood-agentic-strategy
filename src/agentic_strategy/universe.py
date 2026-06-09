from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable


UNIVERSE_FIELDS = [
    "symbol",
    "name",
    "asset_type",
    "tradable",
    "fractional_eligible",
    "active",
    "source",
    "updated_at",
]


@dataclass(frozen=True)
class UniverseRecord:
    symbol: str
    name: str = ""
    asset_type: str = "stock"
    tradable: bool = False
    fractional_eligible: bool = False
    active: bool = False
    source: str = "robinhood_validated"
    updated_at: str = ""


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def merge_universe_records(
    existing: Iterable[UniverseRecord],
    validations: Iterable[UniverseRecord],
) -> list[UniverseRecord]:
    records = {record.symbol: record for record in existing if record.symbol}
    for validation in validations:
        symbol = normalize_symbol(validation.symbol)
        if not symbol:
            continue
        current = records.get(symbol)
        records[symbol] = _merge_record(current, replace(validation, symbol=symbol))
    return [records[symbol] for symbol in sorted(records)]


def read_universe_csv(path: str | Path) -> list[UniverseRecord]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open(newline="") as handle:
        return [_record_from_row(row) for row in csv.DictReader(handle)]


def write_universe_csv(path: str | Path, records: Iterable[UniverseRecord]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNIVERSE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(_row_from_record(record))


def merge_universe_csv(
    *,
    universe_path: str | Path,
    validations_path: str | Path,
    output_path: str | Path | None = None,
) -> list[UniverseRecord]:
    merged = merge_universe_records(
        existing=read_universe_csv(universe_path),
        validations=read_universe_csv(validations_path),
    )
    write_universe_csv(output_path or universe_path, merged)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge Robinhood-validated symbols into universe.csv.")
    parser.add_argument("--universe", required=True, help="Existing canonical universe CSV path.")
    parser.add_argument("--validations", required=True, help="CSV of Robinhood validation results to merge.")
    parser.add_argument("--output", help="Output path. Defaults to overwriting --universe.")
    args = parser.parse_args()

    merged = merge_universe_csv(
        universe_path=args.universe,
        validations_path=args.validations,
        output_path=args.output,
    )
    print(f"wrote {len(merged)} universe records")
    return 0


def _merge_record(current: UniverseRecord | None, validation: UniverseRecord) -> UniverseRecord:
    if current is None:
        return validation
    return UniverseRecord(
        symbol=validation.symbol,
        name=validation.name or current.name,
        asset_type=validation.asset_type or current.asset_type,
        tradable=validation.tradable,
        fractional_eligible=validation.fractional_eligible,
        active=validation.active,
        source=validation.source or current.source,
        updated_at=validation.updated_at or current.updated_at,
    )


def _record_from_row(row: dict[str, str]) -> UniverseRecord:
    return UniverseRecord(
        symbol=normalize_symbol(row.get("symbol", "")),
        name=row.get("name", "").strip(),
        asset_type=row.get("asset_type", "").strip() or "stock",
        tradable=_bool(row.get("tradable")),
        fractional_eligible=_bool(row.get("fractional_eligible")),
        active=_bool(row.get("active")),
        source=row.get("source", "").strip() or "robinhood_validated",
        updated_at=row.get("updated_at", "").strip(),
    )


def _row_from_record(record: UniverseRecord) -> dict[str, str]:
    return {
        "symbol": record.symbol,
        "name": record.name,
        "asset_type": record.asset_type,
        "tradable": _bool_text(record.tradable),
        "fractional_eligible": _bool_text(record.fractional_eligible),
        "active": _bool_text(record.active),
        "source": record.source,
        "updated_at": record.updated_at,
    }


def _bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


if __name__ == "__main__":
    raise SystemExit(main())
