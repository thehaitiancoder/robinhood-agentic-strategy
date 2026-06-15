from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .sold_today import _as_pt as _as_pacific_time


DEFAULT_BUY_MD = Path("data/private/top-10-buy-candidates.md")
DEFAULT_SELL_MD = Path("data/private/top-10-sell-candidates.md")

ZERO = Decimal("0")
MARKET_OPEN_MINUTE_PT = 6 * 60 + 30
MARKET_CLOSE_MINUTE_PT = 13 * 60


@dataclass(frozen=True)
class ReturnCandidate:
    symbol: str
    quantity: Decimal
    average_buy_price: Decimal
    bid_price: Decimal | None
    ask_price: Decimal | None
    last_price: Decimal | None
    last_non_reg_price: Decimal | None = None
    close_price: Decimal | None = None

    @property
    def invested_cost(self) -> Decimal:
        return self.quantity * self.average_buy_price

    @property
    def sell_price(self) -> Decimal | None:
        return self.bid_price if self.bid_price is not None else self.last_price

    @property
    def buy_price(self) -> Decimal | None:
        return self.ask_price if self.ask_price is not None else self.last_price

    def buy_price_for_shortlist(self, *, market_closed: bool = False) -> Decimal | None:
        if market_closed and self.close_price is not None:
            return self.close_price
        if market_closed and self.last_non_reg_price is not None:
            return self.last_non_reg_price
        if market_closed and self.last_price is not None:
            return self.last_price
        return self.buy_price

    @property
    def sell_return_pct(self) -> Decimal | None:
        if self.sell_price is None or self.invested_cost == ZERO:
            return None
        return ((self.sell_price * self.quantity) - self.invested_cost) / self.invested_cost

    @property
    def buy_return_pct(self) -> Decimal | None:
        return self.buy_return_pct_for_shortlist()

    def buy_return_pct_for_shortlist(self, *, market_closed: bool = False) -> Decimal | None:
        buy_price = self.buy_price_for_shortlist(market_closed=market_closed)
        if buy_price is None or self.invested_cost == ZERO:
            return None
        return ((buy_price * self.quantity) - self.invested_cost) / self.invested_cost


def build_return_candidates(
    *,
    positions_payload: dict[str, Any],
    quotes_payload: dict[str, Any],
) -> list[ReturnCandidate]:
    quotes = _quotes_by_symbol(quotes_payload)
    candidates: list[ReturnCandidate] = []
    for position in _positions(positions_payload):
        symbol = _symbol(position)
        quantity = _decimal_or_none(position.get("quantity"))
        average_buy = _decimal_or_none(
            position.get("average_buy_price")
            or position.get("average_price")
            or position.get("avg_buy_price")
        )
        if not symbol or quantity is None or quantity <= ZERO or average_buy is None:
            continue

        quote = quotes.get(symbol, {})
        candidates.append(
            ReturnCandidate(
                symbol=symbol,
                quantity=quantity,
                average_buy_price=average_buy,
                bid_price=_decimal_or_none(quote.get("bid_price")),
                ask_price=_decimal_or_none(quote.get("ask_price")),
                last_price=_decimal_or_none(
                    quote.get("last_trade_price")
                    or quote.get("last_price")
                    or quote.get("last_non_reg_trade_price")
                ),
                last_non_reg_price=_decimal_or_none(quote.get("last_non_reg_trade_price")),
                close_price=_close_price(quote),
            )
        )
    return sorted(candidates, key=lambda item: item.symbol)


def top_buy_candidates(
    candidates: list[ReturnCandidate], *, limit: int = 10, market_closed: bool = False
) -> list[ReturnCandidate]:
    ranked = [
        candidate
        for candidate in candidates
        if candidate.buy_return_pct_for_shortlist(market_closed=market_closed) is not None
    ]
    return sorted(
        ranked,
        key=lambda item: (item.buy_return_pct_for_shortlist(market_closed=market_closed), item.symbol),
    )[:limit]


def top_sell_candidates(candidates: list[ReturnCandidate], *, limit: int = 10) -> list[ReturnCandidate]:
    ranked = [candidate for candidate in candidates if candidate.sell_return_pct is not None]
    return sorted(ranked, key=lambda item: (item.sell_return_pct, item.symbol), reverse=True)[:limit]


def write_shortlists(
    *,
    positions_payload: dict[str, Any],
    quotes_payload: dict[str, Any],
    buy_output: str | Path = DEFAULT_BUY_MD,
    sell_output: str | Path = DEFAULT_SELL_MD,
    generated_at: str | None = None,
    limit: int = 10,
    market_closed: bool | None = None,
) -> tuple[Path, Path]:
    generated = generated_at or _now_utc()
    buy_market_closed = _resolve_market_closed(market_closed)
    candidates = build_return_candidates(
        positions_payload=positions_payload,
        quotes_payload=quotes_payload,
    )
    buy_path = Path(buy_output)
    sell_path = Path(sell_output)
    buy_path.parent.mkdir(parents=True, exist_ok=True)
    sell_path.parent.mkdir(parents=True, exist_ok=True)
    buy_path.write_text(
        render_shortlist(
            title="Top 10 Buy Candidates",
            generated_at=generated,
            candidates=top_buy_candidates(candidates, limit=limit, market_closed=buy_market_closed),
            mode="buy",
            market_closed=buy_market_closed,
        ),
        encoding="utf-8",
    )
    sell_path.write_text(
        render_shortlist(
            title="Top 10 Sell Candidates",
            generated_at=generated,
            candidates=top_sell_candidates(candidates, limit=limit),
            mode="sell",
        ),
        encoding="utf-8",
    )
    return buy_path, sell_path


def render_shortlist(
    *,
    title: str,
    generated_at: str,
    candidates: list[ReturnCandidate],
    mode: str,
    market_closed: bool = False,
) -> str:
    price_side = (
        "official close/last because regular market is closed"
        if mode == "buy" and market_closed
        else "ask/buy-side"
        if mode == "buy"
        else "bid/sell-side"
    )
    lines = [
        f"# {title}",
        "",
        f"Generated: {generated_at}",
        "",
        "Use this file as a speed hint only. Refresh Robinhood before trading.",
        "Update it only after the automation has finished its main execution work.",
        f"Ranking uses {price_side} return from the last recorded broker quote.",
        "",
        "| Rank | Symbol | Return % | Quantity | Avg Buy | Bid | Ask | Last | Non-Reg | Close |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not candidates:
        lines.append("|  | None |  |  |  |  |  |  |  |  |")
    for index, candidate in enumerate(candidates, start=1):
        return_pct = (
            candidate.buy_return_pct_for_shortlist(market_closed=market_closed)
            if mode == "buy"
            else candidate.sell_return_pct
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    candidate.symbol,
                    _pct(return_pct),
                    _num(candidate.quantity),
                    _money(candidate.average_buy_price),
                    _money(candidate.bid_price),
                    _money(candidate.ask_price),
                    _money(candidate.last_price),
                    _money(candidate.last_non_reg_price),
                    _money(candidate.close_price),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate top buy/down and sell/up shortlist documents from broker positions and quotes."
    )
    parser.add_argument("--positions-json", required=True, help="get_equity_positions JSON response.")
    parser.add_argument("--quotes-json", required=True, help="get_equity_quotes JSON response.")
    parser.add_argument("--buy-output", default=str(DEFAULT_BUY_MD))
    parser.add_argument("--sell-output", default=str(DEFAULT_SELL_MD))
    parser.add_argument("--generated-at")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    buy_path, sell_path = write_shortlists(
        positions_payload=_read_json(args.positions_json),
        quotes_payload=_read_json(args.quotes_json),
        buy_output=args.buy_output,
        sell_output=args.sell_output,
        generated_at=args.generated_at,
        limit=args.limit,
    )
    print(buy_path)
    print(sell_path)
    return 0


def _positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _data(payload)
    positions = data.get("positions") if isinstance(data, dict) else None
    return [position for position in positions if isinstance(position, dict)] if isinstance(positions, list) else []


def _quotes_by_symbol(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    data = _data(payload)
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            quote = result.get("quote") if isinstance(result.get("quote"), dict) else result
            if isinstance(quote, dict) and isinstance(result.get("close"), dict):
                quote = {**quote, "close": result["close"]}
            symbol = _symbol(quote)
            if symbol:
                quotes[symbol] = quote
    elif isinstance(data, dict):
        symbol = _symbol(data)
        if symbol:
            quotes[symbol] = data
    return quotes


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def _close_price(quote: dict[str, Any]) -> Decimal | None:
    close = quote.get("close")
    if isinstance(close, dict):
        value = _decimal_or_none(close.get("price"))
        if value is not None:
            return value
    return _decimal_or_none(quote.get("adjusted_previous_close") or quote.get("previous_close"))


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol")).upper()


def _decimal_or_none(value: Any) -> Decimal | None:
    text = _text(value)
    if text == "":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _pct(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{(value * Decimal('100')).quantize(Decimal('0.0001'))}%"


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(Decimal("0.0001")))


def _num(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_market_closed(market_closed: bool | None) -> bool:
    if market_closed is not None:
        return market_closed
    return not _is_regular_market_open_pacific()


def _is_regular_market_open_pacific(now: datetime | None = None) -> bool:
    pt_now = _as_pacific_time(now or datetime.now(timezone.utc))
    minute_of_day = pt_now.hour * 60 + pt_now.minute
    return (
        pt_now.weekday() < 5
        and minute_of_day >= MARKET_OPEN_MINUTE_PT
        and minute_of_day < MARKET_CLOSE_MINUTE_PT
    )


if __name__ == "__main__":
    raise SystemExit(main())
