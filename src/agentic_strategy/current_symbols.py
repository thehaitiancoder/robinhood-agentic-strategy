from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .symbol_policy import (
    DEFAULT_SYMBOL_POLICY_CSV,
    SymbolPolicy,
    is_open_allowed,
    read_symbol_policy_csv,
)
from .universe import UniverseRecord, read_universe_csv


DEFAULT_OUTPUT_JSON = Path("data/private/current-symbols.json")
DEFAULT_SUMMARY_MD = Path("data/private/close-summary.md")

ACTIVE_ORDER_STATES = {
    "new",
    "queued",
    "unconfirmed",
    "confirmed",
    "partially_filled",
}


def build_current_symbols(
    *,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    orders_payload: dict[str, Any],
    account_key: str = "Agentic",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a compact broker-derived current-symbol state.

    This is a cache of Robinhood broker truth at one point in time. It is not a
    market-hours source of truth; refresh broker data before placing orders.
    """

    positions = _position_rows(positions_payload)
    active_orders = _active_order_rows(orders_payload)
    owned_symbols = sorted({row["symbol"] for row in positions})
    active_buy_symbols = sorted(
        {row["symbol"] for row in active_orders if row["side"].lower() == "buy"}
    )
    active_sell_symbols = sorted(
        {row["symbol"] for row in active_orders if row["side"].lower() == "sell"}
    )
    active_order_symbols = sorted({row["symbol"] for row in active_orders})
    blocked_open_symbols = sorted(set(owned_symbols) | set(active_order_symbols))

    return {
        "generated_at": generated_at or _now_utc(),
        "account_key": account_key,
        "source": "robinhood_broker_payloads",
        "warning": "Point-in-time cache. Refresh Robinhood before market-hours trading.",
        "portfolio": _portfolio_row(portfolio_payload),
        "counts": {
            "owned_symbols": len(owned_symbols),
            "active_orders": len(active_orders),
            "active_buy_order_symbols": len(active_buy_symbols),
            "active_sell_order_symbols": len(active_sell_symbols),
            "blocked_open_symbols": len(blocked_open_symbols),
        },
        "owned_symbols": owned_symbols,
        "active_buy_order_symbols": active_buy_symbols,
        "active_sell_order_symbols": active_sell_symbols,
        "active_order_symbols": active_order_symbols,
        "blocked_open_symbols": blocked_open_symbols,
        "positions": positions,
        "active_orders": active_orders,
    }


def select_open_symbols(
    universe: list[UniverseRecord],
    current_symbols: dict[str, Any],
    *,
    limit: int,
    symbol_policies: Mapping[str, SymbolPolicy] | None = None,
) -> list[str]:
    blocked = {symbol.upper() for symbol in current_symbols.get("blocked_open_symbols", [])}
    selected: list[str] = []
    for record in sorted(universe, key=lambda item: item.symbol):
        symbol = record.symbol.upper()
        if len(selected) >= limit:
            break
        if symbol in blocked:
            continue
        if not record.active or not record.tradable or not record.fractional_eligible:
            continue
        if not is_open_allowed(symbol, symbol_policies):
            continue
        selected.append(symbol)
    return selected


def write_current_symbols(
    *,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    orders_payload: dict[str, Any],
    output_json: str | Path = DEFAULT_OUTPUT_JSON,
    summary_md: str | Path | None = DEFAULT_SUMMARY_MD,
    account_key: str = "Agentic",
    generated_at: str | None = None,
    universe: list[UniverseRecord] | None = None,
    open_limit: int = 0,
    symbol_policies: Mapping[str, SymbolPolicy] | None = None,
) -> dict[str, Any]:
    state = build_current_symbols(
        portfolio_payload=portfolio_payload,
        positions_payload=positions_payload,
        orders_payload=orders_payload,
        account_key=account_key,
        generated_at=generated_at,
    )
    if universe is not None and open_limit > 0:
        state["open_candidates"] = select_open_symbols(
            universe,
            state,
            limit=open_limit,
            symbol_policies=symbol_policies,
        )

    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if summary_md is not None:
        summary_path = Path(summary_md)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(render_close_summary(state), encoding="utf-8")

    return state


def render_close_summary(state: dict[str, Any]) -> str:
    portfolio = state.get("portfolio", {})
    lines = [
        "# Robinhood Close Summary",
        "",
        f"Generated: {state.get('generated_at', '')}",
        f"Account: {state.get('account_key', '')}",
        "",
        "This is a post-market broker snapshot. Refresh Robinhood before market-hours trading.",
        "",
        "## Portfolio",
        "",
        f"- Account value: ${portfolio.get('total_value', '0')}",
        f"- Cash: ${portfolio.get('cash', '0')}",
        f"- Buying power: ${portfolio.get('buying_power', '0')}",
        "",
        "## Symbol Counts",
        "",
    ]
    counts = state.get("counts", {})
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")

    lines.extend(["", "## Owned Symbols", ""])
    lines.extend(_symbol_lines(state.get("owned_symbols", [])))
    lines.extend(["", "## Active Buy Order Symbols", ""])
    lines.extend(_symbol_lines(state.get("active_buy_order_symbols", [])))
    lines.extend(["", "## Active Sell Order Symbols", ""])
    lines.extend(_symbol_lines(state.get("active_sell_order_symbols", [])))

    open_candidates = state.get("open_candidates")
    if open_candidates is not None:
        lines.extend(["", "## Open Candidates", ""])
        lines.extend(_symbol_lines(open_candidates))

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a compact broker-derived current-symbol cache and close summary."
    )
    parser.add_argument("--portfolio-json", required=True, help="get_portfolio JSON response.")
    parser.add_argument("--positions-json", required=True, help="get_equity_positions JSON response.")
    parser.add_argument("--orders-json", required=True, help="get_equity_orders JSON response.")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--summary-md", default=str(DEFAULT_SUMMARY_MD))
    parser.add_argument("--account-key", default="Agentic")
    parser.add_argument("--generated-at")
    parser.add_argument("--universe", help="Optional universe CSV for selecting open candidates.")
    parser.add_argument(
        "--symbol-policy",
        default=str(DEFAULT_SYMBOL_POLICY_CSV),
        help="Optional symbol policy CSV. Defaults to data/symbol-policy.csv when present.",
    )
    parser.add_argument(
        "--open-limit",
        type=int,
        default=0,
        help="Optional number of eligible unowned symbols to include from --universe.",
    )
    args = parser.parse_args()

    state = write_current_symbols(
        portfolio_payload=_read_json(args.portfolio_json),
        positions_payload=_read_json(args.positions_json),
        orders_payload=_read_json(args.orders_json),
        output_json=args.output_json,
        summary_md=args.summary_md,
        account_key=args.account_key,
        generated_at=args.generated_at,
        universe=read_universe_csv(args.universe) if args.universe else None,
        open_limit=args.open_limit,
        symbol_policies=read_symbol_policy_csv(args.symbol_policy) if args.symbol_policy else None,
    )
    print(args.output_json)
    if args.summary_md:
        print(args.summary_md)
    if args.open_limit > 0:
        print("open_candidates=" + ",".join(state.get("open_candidates", [])))
    return 0


def _position_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for position in _data(payload).get("positions", []):
        symbol = _symbol(position)
        quantity = _amount(position.get("quantity"))
        if not symbol or _is_zero(quantity) or position.get("type") == "empty":
            continue
        rows.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "sellable_quantity": _amount(position.get("shares_available_for_sells")),
                "average_buy_price": _amount(position.get("average_buy_price")),
                "type": _text(position.get("type")),
            }
        )
    return sorted(rows, key=lambda row: row["symbol"])


def _active_order_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for order in _orders(payload):
        state = _text(order.get("state")).lower()
        if state not in ACTIVE_ORDER_STATES:
            continue
        symbol = _symbol(order)
        if not symbol:
            continue
        amount = order.get("dollar_based_amount") or {}
        rows.append(
            {
                "symbol": symbol,
                "side": _text(order.get("side")).lower(),
                "type": _text(order.get("type")).lower(),
                "state": state,
                "order_id": _text(order.get("id")),
                "dollar_amount": _amount(amount.get("amount")),
                "quantity": _amount(order.get("quantity")),
                "cumulative_quantity": _amount(order.get("cumulative_quantity")),
                "created_at": _text(order.get("created_at")),
                "last_transaction_at": _text(order.get("last_transaction_at")),
            }
        )
    return sorted(rows, key=lambda row: (row["symbol"], row["created_at"], row["order_id"]))


def _portfolio_row(payload: dict[str, Any]) -> dict[str, str]:
    portfolio_payload = payload.get("portfolio")
    data_payload = payload.get("data")
    if isinstance(portfolio_payload, dict):
        portfolio = portfolio_payload
    elif isinstance(data_payload, dict):
        portfolio = data_payload
    else:
        portfolio = payload
    buying_power = portfolio.get("buying_power") or {}
    return {
        "total_value": _amount(portfolio.get("total_value")),
        "cash": _amount(portfolio.get("cash")),
        "buying_power": _amount(buying_power.get("buying_power")),
    }


def _orders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _data(payload)
    orders = data.get("orders") if isinstance(data, dict) else None
    if isinstance(orders, list):
        return [order for order in orders if isinstance(order, dict)]
    order = data.get("order") if isinstance(data, dict) else None
    if isinstance(order, dict):
        return [order]
    return []


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol")).upper()


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _symbol_lines(symbols: list[str]) -> list[str]:
    if not symbols:
        return ["None."]
    return [", ".join(symbols)]


def _amount(value: Any) -> str:
    text = _text(value)
    if text == "":
        return ""
    try:
        return format(Decimal(text).normalize(), "f")
    except InvalidOperation:
        return text


def _is_zero(value: str) -> bool:
    if value == "":
        return True
    try:
        return Decimal(value) == 0
    except InvalidOperation:
        return False


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
