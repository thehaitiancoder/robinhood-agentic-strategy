from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ACTIVE_ORDER_STATES = {"new", "queued", "unconfirmed", "confirmed", "partially_filled"}
ZERO = Decimal("0")
MappingLike = dict[str, Any]


@dataclass(frozen=True)
class DdGuardResult:
    symbol: str
    action: str
    allowed: bool
    trigger_price: Decimal
    price: Decimal | None
    price_basis: str
    reason: str


def check_dd_quote_before_place(
    *,
    symbol: str,
    next_trigger_price: Decimal,
    quote_payload: MappingLike,
) -> DdGuardResult:
    price = _decimal_or_none(_quote(quote_payload).get("ask_price"))
    if price is None:
        return DdGuardResult(
            symbol=symbol.upper(),
            action="block",
            allowed=False,
            trigger_price=next_trigger_price,
            price=None,
            price_basis="ask_price",
            reason="missing executable buy-side ask price for DD preflight",
        )
    if price > next_trigger_price:
        return DdGuardResult(
            symbol=symbol.upper(),
            action="block",
            allowed=False,
            trigger_price=next_trigger_price,
            price=price,
            price_basis="ask_price",
            reason="buy-side ask price is above next DD trigger",
        )
    return DdGuardResult(
        symbol=symbol.upper(),
        action="place",
        allowed=True,
        trigger_price=next_trigger_price,
        price=price,
        price_basis="ask_price",
        reason="buy-side ask price is at or below next DD trigger",
    )


def check_dd_order_after_place(
    *,
    symbol: str,
    next_trigger_price: Decimal,
    order_payload: MappingLike,
) -> DdGuardResult:
    order = _order(order_payload)
    state = str(order.get("state") or "").lower()
    price = _decimal_or_none(order.get("average_price") or order.get("price"))
    basis = "average_price" if order.get("average_price") else "order_price"
    normalized_symbol = (str(order.get("symbol") or symbol)).upper()

    if price is None:
        action = "cancel" if state in ACTIVE_ORDER_STATES else "block"
        return DdGuardResult(
            symbol=normalized_symbol,
            action=action,
            allowed=False,
            trigger_price=next_trigger_price,
            price=None,
            price_basis=basis,
            reason="broker order returned no executable price for DD validation",
        )

    if price > next_trigger_price:
        if state in ACTIVE_ORDER_STATES:
            action = "cancel"
            reason = "queued DD order price is above next DD trigger"
        else:
            action = "filled_above_trigger" if state == "filled" else "block"
            reason = "DD order price is above next DD trigger"
        return DdGuardResult(
            symbol=normalized_symbol,
            action=action,
            allowed=False,
            trigger_price=next_trigger_price,
            price=price,
            price_basis=basis,
            reason=reason,
        )

    return DdGuardResult(
        symbol=normalized_symbol,
        action="keep",
        allowed=True,
        trigger_price=next_trigger_price,
        price=price,
        price_basis=basis,
        reason="broker order price is at or below next DD trigger",
    )


def closed_market_watch_price(quote_payload: MappingLike) -> tuple[Decimal | None, str]:
    close_price = _official_close_price(quote_payload)
    if close_price is not None:
        return close_price, "official_close"

    quote = _quote(quote_payload)
    non_regular = _decimal_or_none(quote.get("last_non_reg_trade_price"))
    if non_regular is not None:
        return non_regular, "last_non_reg_trade_price"

    last_trade = _decimal_or_none(quote.get("last_trade_price") or quote.get("last_price"))
    if last_trade is not None:
        return last_trade, "last_trade_price_fallback"

    return None, "missing_closed_market_watch_price"


def _official_close_price(payload: MappingLike) -> Decimal | None:
    if isinstance(payload, dict):
        close = payload.get("close")
        if isinstance(close, dict):
            value = _decimal_or_none(close.get("price"))
            if value is not None:
                return value
    quote = _quote(payload)
    close = quote.get("close")
    if isinstance(close, dict):
        value = _decimal_or_none(close.get("price"))
        if value is not None:
            return value
    return _decimal_or_none(quote.get("adjusted_previous_close") or quote.get("previous_close"))


def _quote(payload: MappingLike) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("quote"), dict):
        return payload["quote"]
    data = payload.get("data")
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list) and results:
            return _quote(results[0])
        return _quote(data)
    return payload


def _order(payload: MappingLike) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("order"), dict):
        return payload["order"]
    data = payload.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("order"), dict):
            return data["order"]
        orders = data.get("orders")
        if isinstance(orders, list) and orders:
            return orders[0]
    return payload


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed >= ZERO else None


def _result_row(result: DdGuardResult) -> dict[str, str | bool | None]:
    return {
        "symbol": result.symbol,
        "action": result.action,
        "allowed": result.allowed,
        "trigger_price": str(result.trigger_price),
        "price": str(result.price) if result.price is not None else None,
        "price_basis": result.price_basis,
        "reason": result.reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate DD order prices against next trigger price.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--next-trigger-price", required=True)
    parser.add_argument("--quote-json")
    parser.add_argument("--order-json")
    args = parser.parse_args()

    trigger = Decimal(args.next_trigger_price)
    if args.order_json:
        result = check_dd_order_after_place(
            symbol=args.symbol,
            next_trigger_price=trigger,
            order_payload=json.loads(Path(args.order_json).read_text(encoding="utf-8")),
        )
    elif args.quote_json:
        result = check_dd_quote_before_place(
            symbol=args.symbol,
            next_trigger_price=trigger,
            quote_payload=json.loads(Path(args.quote_json).read_text(encoding="utf-8")),
        )
    else:
        parser.error("Pass --quote-json for pre-place validation or --order-json for post-place validation.")
        return 2

    print(json.dumps(_result_row(result), indent=2))
    return 0 if result.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
