from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import (
    Decision,
    PortfolioSnapshot,
    PositionSnapshot,
    QuoteSnapshot,
    StrategyConfig,
    StrategyReport,
    UniverseEntry,
)


def load_config_json(path: str | Path | None) -> StrategyConfig:
    if path is None:
        return StrategyConfig()

    data = json.loads(Path(path).read_text())
    kwargs: dict[str, Any] = {}
    for key in (
        "cash_buffer_pct",
        "max_single_position_pct",
        "profit_take_pct",
        "emergency_sell_min_return_pct",
        "open_base_usd",
        "max_start_share_price_usd",
    ):
        if key in data and data[key] is not None:
            kwargs[key] = Decimal(str(data[key]))
    if "max_new_open_candidates" in data:
        kwargs["max_new_open_candidates"] = int(data["max_new_open_candidates"])
    if data.get("max_start_share_price_usd") is None and "max_start_share_price_usd" in data:
        kwargs["max_start_share_price_usd"] = None
    return StrategyConfig(**kwargs)


def load_portfolio_json(path: str | Path) -> PortfolioSnapshot:
    data = json.loads(Path(path).read_text())
    return PortfolioSnapshot(
        total_value=_decimal(data["total_value"]),
        buying_power=_decimal(data["buying_power"]),
        cash=_optional_decimal(data.get("cash")),
    )


def load_positions_csv(path: str | Path) -> list[PositionSnapshot]:
    rows = _read_csv(path)
    positions: list[PositionSnapshot] = []
    for row in rows:
        positions.append(
            PositionSnapshot(
                symbol=row["symbol"].upper(),
                quantity=_decimal(row["quantity"]),
                invested_cost=_decimal(row["invested_cost"]),
                current_lot_index=int(row.get("current_lot_index") or 1),
                next_trigger_price=_optional_decimal(row.get("next_trigger_price")),
                next_lot_shares=_optional_decimal(row.get("next_lot_shares")),
            )
        )
    return positions


def load_quotes_csv(path: str | Path) -> list[QuoteSnapshot]:
    rows = _read_csv(path)
    quotes: list[QuoteSnapshot] = []
    for row in rows:
        quotes.append(
            QuoteSnapshot(
                symbol=row["symbol"].upper(),
                bid_price=_optional_decimal(row.get("bid_price")),
                ask_price=_optional_decimal(row.get("ask_price")),
                last_price=_optional_decimal(row.get("last_price")),
                updated_at=row.get("updated_at") or None,
            )
        )
    return quotes


def load_universe_csv(path: str | Path) -> list[UniverseEntry]:
    rows = _read_csv(path)
    entries: list[UniverseEntry] = []
    for row in rows:
        entries.append(
            UniverseEntry(
                symbol=row["symbol"].upper(),
                name=row.get("name", ""),
                asset_type=row.get("asset_type") or "stock",
                tradable=_bool(row.get("tradable"), default=True),
                fractional_eligible=_bool(row.get("fractional_eligible"), default=True),
                active=_bool(row.get("active"), default=True),
            )
        )
    return entries


def report_to_json(report: StrategyReport) -> str:
    return json.dumps(_jsonable(report), indent=2, sort_keys=True)


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value).strip())


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return Decimal(text)


def _bool(value: Any, *, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Decision):
        return asdict(value)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value

