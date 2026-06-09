from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .universe import UniverseRecord, write_universe_csv


POSITION_FIELDS = [
    "symbol",
    "quantity",
    "invested_cost",
    "current_lot_index",
    "next_trigger_price",
    "next_lot_shares",
]
QUOTE_FIELDS = ["symbol", "bid_price", "ask_price", "last_price", "updated_at"]


@dataclass(frozen=True)
class BrokerSnapshotFiles:
    portfolio: Path
    positions: Path
    quotes: Path
    universe_validations: Path | None = None


def write_broker_snapshot(
    *,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    quotes_payload: dict[str, Any],
    output_dir: str | Path,
    tradability_payload: dict[str, Any] | None = None,
    position_state_path: str | Path | None = None,
    as_of: str | None = None,
) -> BrokerSnapshotFiles:
    """Normalize broker tool responses into monitor input files."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    position_state = _read_position_state(position_state_path)

    portfolio_path = output_path / "portfolio.json"
    positions_path = output_path / "positions.csv"
    quotes_path = output_path / "quotes.csv"
    validations_path = output_path / "universe.validations.csv" if tradability_payload else None

    portfolio_path.write_text(
        json.dumps(_portfolio_snapshot(portfolio_payload), indent=2, sort_keys=True) + "\n"
    )
    _write_csv(positions_path, POSITION_FIELDS, _position_rows(positions_payload, position_state))
    _write_csv(quotes_path, QUOTE_FIELDS, _quote_rows(quotes_payload))
    if tradability_payload and validations_path:
        write_universe_csv(
            validations_path,
            _universe_records_from_tradability(tradability_payload, as_of=as_of or _today_utc()),
        )

    return BrokerSnapshotFiles(
        portfolio=portfolio_path,
        positions=positions_path,
        quotes=quotes_path,
        universe_validations=validations_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Robinhood tool JSON payloads into monitor snapshot files."
    )
    parser.add_argument("--portfolio-json", required=True, help="get_portfolio JSON response.")
    parser.add_argument("--positions-json", required=True, help="get_equity_positions JSON response.")
    parser.add_argument("--quotes-json", required=True, help="get_equity_quotes JSON response.")
    parser.add_argument("--tradability-json", help="Optional get_equity_tradability JSON response.")
    parser.add_argument(
        "--position-state",
        help="Optional CSV with local ladder state by symbol.",
    )
    parser.add_argument("--output-dir", required=True, help="Directory for normalized snapshot files.")
    parser.add_argument("--as-of", help="Validation date for universe rows. Defaults to UTC today.")
    args = parser.parse_args()

    files = write_broker_snapshot(
        portfolio_payload=_read_json(args.portfolio_json),
        positions_payload=_read_json(args.positions_json),
        quotes_payload=_read_json(args.quotes_json),
        tradability_payload=_read_json(args.tradability_json) if args.tradability_json else None,
        position_state_path=args.position_state,
        output_dir=args.output_dir,
        as_of=args.as_of,
    )
    for path in (files.portfolio, files.positions, files.quotes, files.universe_validations):
        if path:
            print(path)
    return 0


def _portfolio_snapshot(payload: dict[str, Any]) -> dict[str, str]:
    data = _data(payload)
    buying_power = data.get("buying_power") or {}
    return {
        "total_value": _decimal_text(data["total_value"]),
        "buying_power": _decimal_text(buying_power["buying_power"]),
        "cash": _decimal_text(data.get("cash", buying_power["buying_power"])),
    }


def _position_rows(
    payload: dict[str, Any],
    position_state: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for position in _data(payload).get("positions", []):
        symbol = _symbol(position)
        quantity = _decimal(position.get("quantity", "0"))
        if not symbol or quantity <= 0 or position.get("type") == "empty":
            continue

        state = position_state.get(symbol, {})
        invested_cost = state.get("invested_cost") or _invested_cost(position, quantity)
        rows.append(
            {
                "symbol": symbol,
                "quantity": _decimal_text(quantity),
                "invested_cost": invested_cost,
                "current_lot_index": state.get("current_lot_index") or "1",
                "next_trigger_price": state.get("next_trigger_price") or "",
                "next_lot_shares": state.get("next_lot_shares") or "",
            }
        )
    return sorted(rows, key=lambda row: row["symbol"])


def _quote_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for result in _data(payload).get("results", []):
        quote = result.get("quote", result)
        symbol = _symbol(quote)
        if not symbol:
            continue
        last_price, updated_at = _latest_price(quote)
        rows.append(
            {
                "symbol": symbol,
                "bid_price": _optional_decimal_text(quote.get("bid_price")),
                "ask_price": _optional_decimal_text(quote.get("ask_price")),
                "last_price": _optional_decimal_text(last_price),
                "updated_at": updated_at or "",
            }
        )
    return sorted(rows, key=lambda row: row["symbol"])


def _universe_records_from_tradability(
    payload: dict[str, Any],
    *,
    as_of: str,
) -> list[UniverseRecord]:
    records: list[UniverseRecord] = []
    for result in _data(payload).get("results", []):
        symbol = _symbol(result)
        if not symbol:
            continue
        active = result.get("state") == "active"
        account_tradeable = _account_type_tradeable(result)
        records.append(
            UniverseRecord(
                symbol=symbol,
                name=(result.get("name") or result.get("simple_name") or "").strip(),
                asset_type="stock",
                tradable=active and _truthy(result.get("tradeable")) and account_tradeable,
                fractional_eligible=result.get("fractional_tradability") == "tradable",
                active=active,
                source="robinhood_validated",
                updated_at=as_of,
            )
        )
    return sorted(records, key=lambda record: record.symbol)


def _read_position_state(path: str | Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    state_path = Path(path)
    if not state_path.exists():
        return {}
    with state_path.open(newline="") as handle:
        return {
            _symbol(row): {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
            if _symbol(row)
        }


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("data", payload)


def _symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol", "")).strip().upper()


def _invested_cost(position: dict[str, Any], quantity: Decimal) -> str:
    average_buy_price = position.get("average_buy_price")
    if average_buy_price in (None, ""):
        raise ValueError(f"missing invested_cost or average_buy_price for {position.get('symbol')}")
    return _decimal_text(quantity * _decimal(average_buy_price))


def _latest_price(quote: dict[str, Any]) -> tuple[Any, str | None]:
    candidates = [
        (quote.get("last_trade_price"), quote.get("venue_last_trade_time")),
        (quote.get("last_non_reg_trade_price"), quote.get("venue_last_non_reg_trade_time")),
    ]
    valid = [(price, timestamp) for price, timestamp in candidates if price not in (None, "") and timestamp]
    if not valid:
        return quote.get("last_trade_price") or quote.get("last_non_reg_trade_price"), (
            quote.get("venue_last_trade_time") or quote.get("venue_last_non_reg_trade_time")
        )
    return max(valid, key=lambda item: item[1])


def _account_type_tradeable(result: dict[str, Any]) -> bool:
    tradabilities = result.get("account_type_tradabilities") or []
    if not tradabilities:
        return True
    return any(
        item.get("account_type_tradability") == "tradable"
        for item in tradabilities
        if isinstance(item, dict)
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "tradable"}


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value).strip())


def _decimal_text(value: Any) -> str:
    return format(_decimal(value).normalize(), "f")


def _optional_decimal_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return _decimal_text(value)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
