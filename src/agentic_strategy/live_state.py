from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path("data/private/LIVE_STATE.md")
DEFAULT_LEDGER_PATH = Path("data/private/order-ledger.csv")


def write_live_state(
    *,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    orders_payload: dict[str, Any],
    output_path: str | Path = DEFAULT_STATE_PATH,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    account_key: str = "Agentic",
    generated_at: str | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_live_state(
        portfolio_payload=portfolio_payload,
        positions_payload=positions_payload,
        orders_payload=orders_payload,
        ledger_path=ledger_path,
        account_key=account_key,
        generated_at=generated_at,
    )
    path.write_text(markdown)
    return path


def render_live_state(
    *,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    orders_payload: dict[str, Any],
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    account_key: str = "Agentic",
    generated_at: str | None = None,
) -> str:
    generated = generated_at or _now_utc()
    portfolio = _data(portfolio_payload)
    orders = _orders(orders_payload)
    queued_orders = [order for order in orders if _text(order.get("state")).lower() == "queued"]
    active_non_queued_orders = [
        order
        for order in orders
        if _text(order.get("state")).lower() in _ACTIVE_ORDER_STATES
        and _text(order.get("state")).lower() != "queued"
    ]
    positions = _open_positions(positions_payload)
    ledger_rows = _ledger_rows(ledger_path)
    pending_reviewed_opens = _pending_reviewed_opens(
        ledger_rows,
        queued_orders + active_non_queued_orders,
    )

    lines = [
        "# Live Strategy State",
        "",
        "Deprecated legacy snapshot. Do not use this file as the source of truth for trading decisions.",
        "",
        f"Last refreshed: {generated}",
        f"Account: {account_key}",
        "",
        "Refresh Robinhood before placing, reviewing, or cancelling real orders. Use `agentic_strategy.current_symbols` for the current post-market cache workflow.",
        "",
        "## Portfolio",
        "",
        f"- Account value: ${_money(portfolio.get('total_value'))}",
        f"- Cash: ${_money(portfolio.get('cash'))}",
        f"- Buying power: ${_money((portfolio.get('buying_power') or {}).get('buying_power'))}",
        "",
        f"## Queued Orders ({len(queued_orders)})",
        "",
    ]
    lines.extend(_orders_table(queued_orders, empty_message="No queued equity orders."))
    lines.extend(
        [
            "",
            f"## Active Non-Queued Orders ({len(active_non_queued_orders)})",
            "",
        ]
    )
    lines.extend(
        _orders_table(
            active_non_queued_orders,
            empty_message="No active non-queued equity orders.",
        )
    )
    lines.extend(
        [
            "",
            f"## Reviewed Opens Pending Confirmation ({len(pending_reviewed_opens)})",
            "",
        ]
    )
    lines.extend(_pending_reviews_table(pending_reviewed_opens))
    lines.extend(["", f"## Open Equity Positions ({len(positions)})", ""])
    lines.extend(_positions_table(positions))
    lines.extend(["", "## Ledger", ""])
    lines.extend(_ledger_summary(ledger_rows))
    lines.extend(
        [
            "",
            "## Deprecated Flow",
            "",
            "1. Do not use this file to decide whether to trade.",
            "2. Refresh Robinhood portfolio, positions, orders, and fills.",
            "3. During market hours, evaluate directly from live broker data.",
            "4. After close, generate `data/private/current-symbols.json` and `data/private/close-summary.md`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the private live strategy state summary.")
    parser.add_argument("--portfolio-json", required=True, help="get_portfolio JSON response.")
    parser.add_argument("--positions-json", required=True, help="get_equity_positions JSON response.")
    parser.add_argument("--orders-json", required=True, help="get_equity_orders JSON response.")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER_PATH))
    parser.add_argument("--output", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--account-key", default="Agentic")
    parser.add_argument("--generated-at")
    args = parser.parse_args()

    path = write_live_state(
        portfolio_payload=_read_json(args.portfolio_json),
        positions_payload=_read_json(args.positions_json),
        orders_payload=_read_json(args.orders_json),
        output_path=args.output,
        ledger_path=args.ledger,
        account_key=args.account_key,
        generated_at=args.generated_at,
    )
    print(path)
    return 0


def _orders_table(
    orders: list[dict[str, Any]],
    *,
    empty_message: str = "No matching equity orders.",
) -> list[str]:
    if not orders:
        return [empty_message]
    rows = [
        "| Symbol | Side | Type | State | Amount | Order Qty | Filled Qty | Created | Order ID |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for order in sorted(orders, key=lambda item: (_text(item.get("symbol")), _text(item.get("created_at")))):
        amount = (order.get("dollar_based_amount") or {}).get("amount")
        rows.append(
            "| "
            + " | ".join(
                [
                    _text(order.get("symbol")) or "(unknown)",
                    _text(order.get("side")),
                    _text(order.get("type")),
                    _text(order.get("state")),
                    f"${_money(amount)}" if _text(amount) else "",
                    _amount(order.get("quantity")),
                    _amount(order.get("cumulative_quantity")),
                    _text(order.get("created_at")),
                    _text(order.get("id")),
                ]
            )
            + " |"
        )
    return rows


def _positions_table(positions: list[dict[str, Any]]) -> list[str]:
    if not positions:
        return ["No open equity positions. Queued buys are listed separately above."]
    rows = [
        "| Symbol | Type | Quantity | Sellable | Average Buy |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for position in sorted(positions, key=lambda item: _text(item.get("symbol"))):
        average_buy = position.get("average_buy_price")
        rows.append(
            "| "
            + " | ".join(
                [
                    _text(position.get("symbol")),
                    _text(position.get("type")),
                    _amount(position.get("quantity")),
                    _amount(position.get("shares_available_for_sells")),
                    f"${_money(average_buy)}" if _text(average_buy) else "",
                ]
            )
            + " |"
        )
    return rows


def _pending_reviews_table(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["No reviewed openings are waiting for user confirmation."]
    table = [
        "| Symbol | Side | Type | Amount | Reviewed | Reason | Payload Ref |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        amount = row.get("dollar_amount")
        table.append(
            "| "
            + " | ".join(
                [
                    row.get("symbol", ""),
                    row.get("side", ""),
                    row.get("order_type", ""),
                    f"${_money(amount)}" if _text(amount) else "",
                    row.get("recorded_at", ""),
                    row.get("reason", ""),
                    row.get("payload_ref", ""),
                ]
            )
            + " |"
        )
    return table


def _ledger_summary(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["No local ledger rows recorded yet."]
    counts: dict[str, int] = {}
    for row in rows:
        event_type = row.get("event_type") or "unknown"
        counts[event_type] = counts.get(event_type, 0) + 1
    latest = max(rows, key=lambda row: row.get("recorded_at", ""))
    summary = [
        f"- Ledger path: `data/private/order-ledger.csv`",
        f"- Total rows: {len(rows)}",
        f"- Latest row: {latest.get('recorded_at', '')} `{latest.get('event_type', '')}` {latest.get('symbol', '')}".rstrip(),
    ]
    for event_type in sorted(counts):
        summary.append(f"- {event_type}: {counts[event_type]}")
    return summary


def _pending_reviewed_opens(
    ledger_rows: list[dict[str, str]],
    active_orders: list[dict[str, Any]],
) -> list[dict[str, str]]:
    active_order_keys = {_order_match_key(order) for order in active_orders}
    order_rows = [row for row in ledger_rows if row.get("event_type") == "order"]
    pending_by_key: dict[tuple[str, str, str, str], dict[str, str]] = {}

    for row in ledger_rows:
        if not _is_opening_review(row):
            continue
        key = _ledger_match_key(row)
        if key in active_order_keys:
            continue
        reviewed_at = row.get("recorded_at", "")
        if any(
            _ledger_match_key(order_row) == key
            and order_row.get("recorded_at", "") >= reviewed_at
            for order_row in order_rows
        ):
            continue
        existing = pending_by_key.get(key)
        if existing is None or row.get("recorded_at", "") >= existing.get("recorded_at", ""):
            pending_by_key[key] = row

    return sorted(
        pending_by_key.values(),
        key=lambda row: (row.get("recorded_at", ""), row.get("symbol", "")),
    )


def _is_opening_review(row: dict[str, str]) -> bool:
    return (
        row.get("event_type") == "review"
        and row.get("side") == "buy"
        and row.get("order_type") == "market"
        and _text(row.get("symbol")) != ""
        and _text(row.get("dollar_amount")) != ""
    )


def _ledger_match_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        _text(row.get("symbol")).upper(),
        _text(row.get("side")).lower(),
        _text(row.get("order_type")).lower(),
        _amount(row.get("dollar_amount")),
    )


def _order_match_key(order: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(order.get("symbol")).upper(),
        _text(order.get("side")).lower(),
        _text(order.get("type")).lower(),
        _amount((order.get("dollar_based_amount") or {}).get("amount")),
    )


def _open_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    positions = []
    for position in _data(payload).get("positions", []):
        if _amount(position.get("quantity")) == "0" or position.get("type") == "empty":
            continue
        positions.append(position)
    return positions


def _orders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _data(payload)
    orders = data.get("orders") if isinstance(data, dict) else None
    if isinstance(orders, list):
        return [order for order in orders if isinstance(order, dict)]
    order = data.get("order") if isinstance(data, dict) else None
    if isinstance(order, dict):
        return [order]
    return []


_ACTIVE_ORDER_STATES = {
    "new",
    "queued",
    "unconfirmed",
    "confirmed",
    "partially_filled",
}


def _ledger_rows(path: str | Path) -> list[dict[str, str]]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    with ledger_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def _money(value: Any) -> str:
    amount = _amount(value)
    if amount == "":
        return "0"
    return amount


def _amount(value: Any) -> str:
    text = _text(value)
    if text == "":
        return ""
    try:
        return format(Decimal(text).normalize(), "f")
    except InvalidOperation:
        return text


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
