from __future__ import annotations

import argparse
import csv
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


DEFAULT_LEDGER_PATH = Path("data/private/order-ledger.csv")

LEDGER_FIELDS = [
    "ledger_event_id",
    "recorded_at",
    "account_key",
    "event_type",
    "symbol",
    "side",
    "order_type",
    "order_state",
    "dollar_amount",
    "quantity",
    "cumulative_quantity",
    "limit_price",
    "stop_price",
    "average_price",
    "estimated_price",
    "fees",
    "time_in_force",
    "market_hours",
    "order_id",
    "ref_id",
    "placed_agent",
    "broker_created_at",
    "broker_last_transaction_at",
    "reason",
    "alerts",
    "market_data_disclosure",
    "source",
    "payload_ref",
    "raw_event_key",
]

NUMERIC_FIELDS = {
    "dollar_amount",
    "quantity",
    "cumulative_quantity",
    "limit_price",
    "stop_price",
    "average_price",
    "estimated_price",
    "fees",
}


@dataclass(frozen=True)
class AppendResult:
    ledger_path: Path
    appended: int
    duplicates: int


def append_ledger_events(
    ledger_path: str | Path,
    events: Iterable[dict[str, Any]],
) -> AppendResult:
    """Append events to the local private ledger, skipping known raw event keys."""

    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_ledger_row(event) for event in events]

    with _ledger_lock(path):
        existing_keys, existing_semantic_keys = _existing_event_keys(path)
        write_header = not path.exists() or path.stat().st_size == 0

        appended = 0
        duplicates = 0
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            for row in rows:
                raw_key = row["raw_event_key"]
                semantic_key = _semantic_event_key(row)
                if raw_key in existing_keys or (
                    semantic_key != "" and semantic_key in existing_semantic_keys
                ):
                    duplicates += 1
                    continue
                writer.writerow(row)
                existing_keys.add(raw_key)
                if semantic_key:
                    existing_semantic_keys.add(semantic_key)
                appended += 1

    return AppendResult(ledger_path=path, appended=appended, duplicates=duplicates)


def review_events_from_payload(
    payload: dict[str, Any],
    *,
    account_key: str = "",
    payload_ref: str = "",
    reason: str = "broker order review",
) -> list[dict[str, str]]:
    data = _data(payload)
    quote = data.get("quote_data") or {}
    symbol = _symbol(data.get("symbol") or quote.get("symbol"))
    side = _text(data.get("side"))
    order_type = _text(data.get("type"))
    dollar_amount = _amount(data.get("dollar_amount"))
    quantity = _amount(data.get("quantity"))
    disclosure = _text(data.get("market_data_disclosure"))
    alerts = _compact_json(data.get("order_checks") or {})

    return [
        new_ledger_event(
            account_key=account_key,
            event_type="review",
            symbol=symbol,
            side=side,
            order_type=order_type,
            dollar_amount=dollar_amount,
            quantity=quantity,
            estimated_price=_latest_quote_price(quote),
            time_in_force=_text(data.get("time_in_force")),
            market_hours=_text(data.get("market_hours")),
            reason=reason,
            alerts=alerts,
            market_data_disclosure=disclosure,
            source="review_equity_order",
            payload_ref=payload_ref,
            raw_event_key=_join_key(
                "review",
                payload_ref,
                symbol,
                side,
                order_type,
                dollar_amount,
                quantity,
                disclosure,
            ),
        )
    ]


def order_events_from_payload(
    payload: dict[str, Any],
    *,
    account_key: str = "",
    payload_ref: str = "",
    reason: str = "broker order snapshot",
) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for order in _orders(payload):
        events.append(
            order_event_from_order(
                order,
                account_key=account_key,
                payload_ref=payload_ref,
                reason=reason,
            )
        )
        events.extend(
            fill_events_from_order(
                order,
                account_key=account_key,
                payload_ref=payload_ref,
            )
        )
    return events


def order_event_from_order(
    order: dict[str, Any],
    *,
    account_key: str = "",
    payload_ref: str = "",
    reason: str = "broker order snapshot",
) -> dict[str, str]:
    state = _text(order.get("state")).lower()
    event_type = {
        "cancelled": "cancel",
        "rejected": "reject",
        "failed": "reject",
        "voided": "reject",
    }.get(state, "order")
    return _event_from_order(
        order,
        account_key=account_key,
        event_type=event_type,
        payload_ref=payload_ref,
        reason=reason,
        raw_event_key=_order_raw_key(order),
    )


def fill_events_from_order(
    order: dict[str, Any],
    *,
    account_key: str = "",
    payload_ref: str = "",
) -> list[dict[str, str]]:
    executions = order.get("executions") or []
    if executions:
        return [
            _fill_event_from_execution(
                order,
                execution,
                index=index,
                account_key=account_key,
                payload_ref=payload_ref,
            )
            for index, execution in enumerate(executions)
            if isinstance(execution, dict)
        ]

    state = _text(order.get("state")).lower()
    cumulative_quantity = _amount(order.get("cumulative_quantity"))
    if state not in {"filled", "partially_filled"} or _is_zero(cumulative_quantity):
        return []

    return [
        _event_from_order(
            order,
            account_key=account_key,
            event_type="fill",
            payload_ref=payload_ref,
            reason="order fill summary from broker order state",
            raw_event_key=_join_key(
                "fill-summary",
                order.get("id"),
                order.get("last_transaction_at"),
                cumulative_quantity,
                order.get("average_price"),
            ),
        )
    ]


def new_ledger_event(**values: Any) -> dict[str, str]:
    row = {field: "" for field in LEDGER_FIELDS}
    row["ledger_event_id"] = str(uuid4())
    row["recorded_at"] = _now_utc()
    row["source"] = "manual"
    for key, value in values.items():
        if key in row:
            row[key] = _amount(value) if key in NUMERIC_FIELDS else _text(value)
    if not row["raw_event_key"]:
        row["raw_event_key"] = _join_key(
            row["source"],
            row["event_type"],
            row["order_id"],
            row["symbol"],
            row["ledger_event_id"],
        )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Append events to the private strategy order ledger.")
    parser.add_argument(
        "--ledger",
        default=str(DEFAULT_LEDGER_PATH),
        help="Ledger CSV path. Defaults to data/private/order-ledger.csv.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("record-review", help="Record an order review preview.")
    _add_account_args(review)
    review.add_argument("--review-json", help="Optional review_equity_order JSON payload.")
    review.add_argument("--symbol")
    review.add_argument("--side")
    review.add_argument("--order-type")
    review.add_argument("--dollar-amount")
    review.add_argument("--quantity")
    review.add_argument("--estimated-price")
    review.add_argument("--time-in-force")
    review.add_argument("--market-hours")
    review.add_argument("--alerts", default="{}")
    review.add_argument("--market-data-disclosure", default="")
    review.add_argument("--reason", default="broker order review")

    order = subparsers.add_parser("record-order", help="Record a placed order or order status.")
    _add_account_args(order)
    order.add_argument("--symbol", required=True)
    order.add_argument("--side", required=True)
    order.add_argument("--order-type", required=True)
    order.add_argument("--order-state", required=True)
    order.add_argument("--order-id")
    order.add_argument("--ref-id")
    order.add_argument("--dollar-amount")
    order.add_argument("--quantity")
    order.add_argument("--cumulative-quantity")
    order.add_argument("--limit-price")
    order.add_argument("--stop-price")
    order.add_argument("--average-price")
    order.add_argument("--estimated-price")
    order.add_argument("--fees")
    order.add_argument("--time-in-force")
    order.add_argument("--market-hours")
    order.add_argument("--placed-agent")
    order.add_argument("--broker-created-at")
    order.add_argument("--broker-last-transaction-at")
    order.add_argument("--reason", default="manual broker order record")

    skipped = subparsers.add_parser("record-skip", help="Record a skipped action with its reason.")
    _add_account_args(skipped)
    skipped.add_argument("--symbol")
    skipped.add_argument("--reason", required=True)
    skipped.add_argument("--source", default="manual_skip")

    imports = subparsers.add_parser("import-orders", help="Import get_equity_orders or place order JSON.")
    _add_account_args(imports)
    imports.add_argument("--orders-json", required=True)
    imports.add_argument("--reason", default="broker order history import")

    args = parser.parse_args()
    events = _events_from_args(args)
    result = append_ledger_events(args.ledger, events)
    print(
        f"{result.ledger_path}: appended {result.appended} event(s), "
        f"skipped {result.duplicates} duplicate(s)"
    )
    return 0


def _events_from_args(args: argparse.Namespace) -> list[dict[str, str]]:
    if args.command == "record-review":
        if args.review_json:
            return review_events_from_payload(
                _read_json(args.review_json),
                account_key=args.account_key,
                payload_ref=args.payload_ref or args.review_json,
                reason=args.reason,
            )
        _require(args.symbol, "--symbol")
        _require(args.side, "--side")
        _require(args.order_type, "--order-type")
        return [
            new_ledger_event(
                account_key=args.account_key,
                event_type="review",
                symbol=_symbol(args.symbol),
                side=args.side,
                order_type=args.order_type,
                dollar_amount=args.dollar_amount,
                quantity=args.quantity,
                estimated_price=args.estimated_price,
                time_in_force=args.time_in_force,
                market_hours=args.market_hours,
                reason=args.reason,
                alerts=args.alerts,
                market_data_disclosure=args.market_data_disclosure,
                source="manual_review",
                payload_ref=args.payload_ref,
            )
        ]

    if args.command == "record-order":
        return [
            new_ledger_event(
                account_key=args.account_key,
                event_type=_manual_order_event_type(args.order_state),
                symbol=_symbol(args.symbol),
                side=args.side,
                order_type=args.order_type,
                order_state=args.order_state,
                dollar_amount=args.dollar_amount,
                quantity=args.quantity,
                cumulative_quantity=args.cumulative_quantity,
                limit_price=args.limit_price,
                stop_price=args.stop_price,
                average_price=args.average_price,
                estimated_price=args.estimated_price,
                fees=args.fees,
                time_in_force=args.time_in_force,
                market_hours=args.market_hours,
                order_id=args.order_id,
                ref_id=args.ref_id,
                placed_agent=args.placed_agent,
                broker_created_at=args.broker_created_at,
                broker_last_transaction_at=args.broker_last_transaction_at,
                reason=args.reason,
                source="manual_order",
                payload_ref=args.payload_ref,
            )
        ]

    if args.command == "record-skip":
        return [
            new_ledger_event(
                account_key=args.account_key,
                event_type="skip",
                symbol=_symbol(args.symbol),
                reason=args.reason,
                source=args.source,
                payload_ref=args.payload_ref,
            )
        ]

    if args.command == "import-orders":
        return order_events_from_payload(
            _read_json(args.orders_json),
            account_key=args.account_key,
            payload_ref=args.payload_ref or args.orders_json,
            reason=args.reason,
        )

    raise ValueError(f"unsupported command: {args.command}")


def _event_from_order(
    order: dict[str, Any],
    *,
    account_key: str,
    event_type: str,
    payload_ref: str,
    reason: str,
    raw_event_key: str,
) -> dict[str, str]:
    dollar_based_amount = order.get("dollar_based_amount") or {}
    return new_ledger_event(
        account_key=account_key,
        event_type=event_type,
        symbol=_symbol(order.get("symbol")),
        side=order.get("side"),
        order_type=order.get("type"),
        order_state=order.get("state"),
        dollar_amount=dollar_based_amount.get("amount"),
        quantity=order.get("quantity"),
        cumulative_quantity=order.get("cumulative_quantity"),
        limit_price=order.get("limit_price") or order.get("price") if order.get("type") == "limit" else "",
        stop_price=order.get("stop_price"),
        average_price=order.get("average_price"),
        estimated_price=order.get("price"),
        fees=order.get("fees"),
        time_in_force=order.get("time_in_force"),
        market_hours=order.get("market_hours"),
        order_id=order.get("id"),
        placed_agent=order.get("placed_agent"),
        broker_created_at=order.get("created_at"),
        broker_last_transaction_at=order.get("last_transaction_at"),
        reason=reason,
        source="broker_order",
        payload_ref=payload_ref,
        raw_event_key=raw_event_key,
    )


def _fill_event_from_execution(
    order: dict[str, Any],
    execution: dict[str, Any],
    *,
    index: int,
    account_key: str,
    payload_ref: str,
) -> dict[str, str]:
    timestamp = (
        execution.get("timestamp")
        or execution.get("created_at")
        or execution.get("executed_at")
        or execution.get("settlement_date")
        or order.get("last_transaction_at")
    )
    quantity = execution.get("quantity") or execution.get("shares") or execution.get("amount")
    price = execution.get("price") or execution.get("average_price")
    return new_ledger_event(
        account_key=account_key,
        event_type="fill",
        symbol=_symbol(order.get("symbol")),
        side=order.get("side"),
        order_type=order.get("type"),
        order_state=order.get("state"),
        dollar_amount=(order.get("dollar_based_amount") or {}).get("amount"),
        quantity=quantity,
        cumulative_quantity=order.get("cumulative_quantity"),
        average_price=price or order.get("average_price"),
        estimated_price=order.get("price"),
        fees=execution.get("fees") or order.get("fees"),
        time_in_force=order.get("time_in_force"),
        market_hours=order.get("market_hours"),
        order_id=order.get("id"),
        placed_agent=order.get("placed_agent"),
        broker_created_at=order.get("created_at"),
        broker_last_transaction_at=timestamp,
        reason="broker execution fill",
        source="broker_execution",
        payload_ref=payload_ref,
        raw_event_key=_join_key(
            "fill",
            order.get("id"),
            execution.get("id") or index,
            timestamp,
            quantity,
            price,
        ),
    )


def _orders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _data(payload)
    if isinstance(data, dict):
        orders = data.get("orders")
        if isinstance(orders, list):
            return [order for order in orders if isinstance(order, dict)]
        order = data.get("order")
        if isinstance(order, dict):
            return [order]

    orders = payload.get("orders")
    if isinstance(orders, list):
        return [order for order in orders if isinstance(order, dict)]
    if _looks_like_order(payload):
        return [payload]
    return []


def _data(payload: dict[str, Any]) -> Any:
    return payload.get("data", payload)


def _looks_like_order(payload: dict[str, Any]) -> bool:
    return "id" in payload and "side" in payload and "state" in payload


def _manual_order_event_type(state: str) -> str:
    normalized = _text(state).lower()
    if normalized == "cancelled":
        return "cancel"
    if normalized in {"rejected", "failed", "voided"}:
        return "reject"
    return "order"


def _order_raw_key(order: dict[str, Any]) -> str:
    return _join_key(
        "order",
        order.get("id"),
        order.get("state"),
        order.get("last_transaction_at"),
        order.get("cumulative_quantity"),
        order.get("average_price"),
    )


def _latest_quote_price(quote: dict[str, Any]) -> str:
    prices = [
        (quote.get("last_trade_price"), quote.get("venue_last_trade_time")),
        (quote.get("last_non_reg_trade_price"), quote.get("venue_last_non_reg_trade_time")),
    ]
    valid = [(price, timestamp) for price, timestamp in prices if price not in (None, "") and timestamp]
    if valid:
        return _amount(max(valid, key=lambda item: item[1])[0])
    return _amount(quote.get("last_trade_price") or quote.get("last_non_reg_trade_price"))


def _existing_event_keys(path: Path) -> tuple[set[str], set[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set(), set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return (
        {row.get("raw_event_key", "") for row in rows if row.get("raw_event_key")},
        {key for key in (_semantic_event_key(row) for row in rows) if key},
    )


def _ledger_row(event: dict[str, Any]) -> dict[str, str]:
    row = {
        field: _amount(event.get(field)) if field in NUMERIC_FIELDS else _text(event.get(field))
        for field in LEDGER_FIELDS
    }
    if not row["ledger_event_id"]:
        row["ledger_event_id"] = str(uuid4())
    if not row["recorded_at"]:
        row["recorded_at"] = _now_utc()
    if not row["raw_event_key"]:
        row["raw_event_key"] = _join_key(
            row["source"],
            row["event_type"],
            row["order_id"],
            row["symbol"],
            row["ledger_event_id"],
        )
    return row


@contextmanager
def _ledger_lock(path: Path) -> Any:
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + 10
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for ledger lock {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _semantic_event_key(row: dict[str, str]) -> str:
    order_id = row.get("order_id", "")
    if not order_id:
        return ""
    return _join_key(
        "semantic",
        row.get("event_type"),
        order_id,
        row.get("order_state"),
        row.get("broker_last_transaction_at"),
        row.get("cumulative_quantity"),
        row.get("average_price"),
    )


def _add_account_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--account-key",
        default="",
        help="Non-sensitive account label such as Agentic or masked last four; do not use full account numbers.",
    )
    parser.add_argument("--payload-ref", default="", help="File path or note identifying the source payload.")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _symbol(value: Any) -> str:
    return _text(value).upper()


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


def _join_key(*parts: Any) -> str:
    return ":".join(_text(part).replace("\n", " ") for part in parts if _text(part) != "")


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require(value: Any, flag: str) -> None:
    if _text(value) == "":
        raise SystemExit(f"{flag} is required unless --review-json is provided")


if __name__ == "__main__":
    raise SystemExit(main())
