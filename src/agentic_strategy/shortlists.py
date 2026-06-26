from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

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

    def sell_price_for_shortlist(self, *, market_closed: bool = False) -> Decimal | None:
        if market_closed and self.close_price is not None:
            return self.close_price
        if market_closed and self.last_non_reg_price is not None:
            return self.last_non_reg_price
        if market_closed and self.last_price is not None:
            return self.last_price
        return self.sell_price

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
        return self.sell_return_pct_for_shortlist()

    def sell_return_pct_for_shortlist(self, *, market_closed: bool = False) -> Decimal | None:
        sell_price = self.sell_price_for_shortlist(market_closed=market_closed)
        if sell_price is None or self.invested_cost == ZERO:
            return None
        return ((sell_price * self.quantity) - self.invested_cost) / self.invested_cost

    @property
    def buy_return_pct(self) -> Decimal | None:
        return self.buy_return_pct_for_shortlist()

    def buy_return_pct_for_shortlist(self, *, market_closed: bool = False) -> Decimal | None:
        buy_price = self.buy_price_for_shortlist(market_closed=market_closed)
        if buy_price is None or self.invested_cost == ZERO:
            return None
        return ((buy_price * self.quantity) - self.invested_cost) / self.invested_cost


@dataclass(frozen=True)
class DoubleDownShortlistCandidate:
    symbol: str
    trigger_gap_pct: Decimal
    buy_price: Decimal
    trigger_price: Decimal
    lot: str
    due_qty: Decimal | None
    integer_qty: Decimal | None
    decimal_left: Decimal | None
    active_buy_count: int
    status: str


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


def top_sell_candidates(
    candidates: list[ReturnCandidate], *, limit: int = 10, market_closed: bool = False
) -> list[ReturnCandidate]:
    ranked = [
        candidate
        for candidate in candidates
        if candidate.sell_return_pct_for_shortlist(market_closed=market_closed) is not None
    ]
    return sorted(
        ranked,
        key=lambda item: (item.sell_return_pct_for_shortlist(market_closed=market_closed), item.symbol),
        reverse=True,
    )[:limit]


def write_shortlists(
    *,
    positions_payload: dict[str, Any],
    quotes_payload: dict[str, Any],
    dd_scan_payload: dict[str, Any] | None = None,
    buy_output: str | Path = DEFAULT_BUY_MD,
    sell_output: str | Path = DEFAULT_SELL_MD,
    generated_at: str | None = None,
    limit: int = 10,
    market_closed: bool | None = None,
) -> tuple[Path, Path]:
    generated = generated_at or _now_utc()
    resolved_market_closed = _resolve_market_closed(market_closed)
    candidates = build_return_candidates(
        positions_payload=positions_payload,
        quotes_payload=quotes_payload,
    )
    buy_path = Path(buy_output)
    sell_path = Path(sell_output)
    buy_path.parent.mkdir(parents=True, exist_ok=True)
    sell_path.parent.mkdir(parents=True, exist_ok=True)
    if dd_scan_payload is not None:
        buy_text = render_dd_shortlist(
            generated_at=generated,
            candidates=top_dd_candidates(dd_scan_payload, limit=limit),
        )
    else:
        buy_text = render_shortlist(
            title="Top 10 Buy Candidates",
            generated_at=generated,
            candidates=top_buy_candidates(candidates, limit=limit, market_closed=resolved_market_closed),
            mode="buy",
            market_closed=resolved_market_closed,
        )
    buy_path.write_text(buy_text, encoding="utf-8")
    sell_path.write_text(
        render_shortlist(
            title="Top 10 Sell Candidates",
            generated_at=generated,
            candidates=top_sell_candidates(candidates, limit=limit, market_closed=resolved_market_closed),
            mode="sell",
            market_closed=resolved_market_closed,
        ),
        encoding="utf-8",
    )
    return buy_path, sell_path


def top_dd_candidates(scan_payload: dict[str, Any], *, limit: int = 10) -> list[DoubleDownShortlistCandidate]:
    by_symbol: dict[str, DoubleDownShortlistCandidate] = {}
    for row in _scan_rows(scan_payload, "exact_share_dd"):
        candidate = _due_dd_shortlist_candidate(row)
        if candidate is not None and candidate.status != "due-fractional":
            _keep_best_dd_candidate(by_symbol, candidate)
    for row in _scan_rows(scan_payload, "dd_watch"):
        candidate = _watch_dd_shortlist_candidate(row)
        if candidate is not None:
            _keep_best_dd_candidate(by_symbol, candidate)
    return sorted(
        by_symbol.values(),
        key=lambda item: (item.active_buy_count > 0, item.trigger_gap_pct, item.symbol),
    )[:limit]


def render_dd_shortlist(
    *,
    generated_at: str,
    candidates: list[DoubleDownShortlistCandidate],
) -> str:
    lines = [
        "# Top 10 Buy/DD Candidates",
        "",
        f"Generated: {generated_at}",
        "",
        "Use this file as a speed hint only. Refresh Robinhood before trading.",
        "Update it only after the automation has finished its main execution work.",
        "Ranking uses exact DD trigger proximity from reconstructed lot history.",
        "Gap % is `(buy price - trigger) / trigger`; zero or negative means DD is due.",
        "Exact due rows with integer quantity below 1 are excluded; they are handled with a later combined lot or manually.",
        "",
        "| Rank | Symbol | Gap % | Status | Buy Price | Trigger | Lot | Due Qty | Integer Qty | Decimal Left | Active Buy |",
        "| ---: | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    if not candidates:
        lines.append("|  | None |  |  |  |  |  |  |  |  |  |")
    for index, candidate in enumerate(candidates, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    candidate.symbol,
                    _pct_from_percent(candidate.trigger_gap_pct),
                    candidate.status,
                    _money(candidate.buy_price),
                    _money(candidate.trigger_price),
                    candidate.lot,
                    _maybe_num(candidate.due_qty),
                    _maybe_num(candidate.integer_qty),
                    _maybe_num(candidate.decimal_left),
                    str(candidate.active_buy_count),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


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
        if market_closed
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
            else candidate.sell_return_pct_for_shortlist(market_closed=market_closed)
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
    parser.add_argument("--dd-scan-json", help="Optional afterhours_scan JSON report for exact DD proximity ranking.")
    parser.add_argument("--buy-output", default=str(DEFAULT_BUY_MD))
    parser.add_argument("--sell-output", default=str(DEFAULT_SELL_MD))
    parser.add_argument("--generated-at")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    buy_path, sell_path = write_shortlists(
        positions_payload=_read_json(args.positions_json),
        quotes_payload=_read_json(args.quotes_json),
        dd_scan_payload=_read_json(args.dd_scan_json) if args.dd_scan_json else None,
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
    quote_rows = data.get("quotes") if isinstance(data, dict) else None
    if isinstance(quote_rows, list):
        for quote_row in quote_rows:
            if not isinstance(quote_row, dict):
                continue
            normalized = _normalize_quote_row(cast(dict[str, Any], quote_row))
            symbol = _symbol(normalized)
            if symbol:
                quotes[symbol] = normalized
        if quotes:
            return quotes
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            result_row = cast(dict[str, Any], result)
            quote_payload = result_row.get("quote")
            quote = cast(dict[str, Any], quote_payload) if isinstance(quote_payload, dict) else result_row
            close_payload = result_row.get("close")
            if isinstance(close_payload, dict):
                quote = {**quote, "close": close_payload}
            symbol = _symbol(quote)
            if symbol:
                quotes[symbol] = quote
    elif isinstance(data, dict):
        symbol = _symbol(data)
        if symbol:
            quotes[symbol] = data
    return quotes


def _normalize_quote_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw")
    if isinstance(raw, dict):
        quote_payload = raw.get("quote")
        quote = cast(dict[str, Any], quote_payload) if isinstance(quote_payload, dict) else {}
        close_payload = raw.get("close")
        if isinstance(close_payload, dict):
            quote = {**quote, "close": close_payload}
        if quote:
            return quote
    return {
        "symbol": row.get("symbol"),
        "bid_price": row.get("bid"),
        "ask_price": row.get("ask"),
        "last_trade_price": row.get("last_trade") or row.get("last"),
        "last_non_reg_trade_price": row.get("last_non_reg"),
        "close": {"price": row.get("close")} if row.get("close") not in (None, "") else None,
    }


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


def _scan_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = _data(payload).get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _due_dd_shortlist_candidate(row: dict[str, Any]) -> DoubleDownShortlistCandidate | None:
    buy_price = _decimal_or_none(row.get("buy_price"))
    trigger = _decimal_or_none(row.get("deepest_trigger"))
    if buy_price is None or trigger is None or trigger <= ZERO:
        return None
    due_qty = _decimal_or_none(row.get("due_qty"))
    integer_qty = _decimal_or_none(row.get("integer_qty"))
    return DoubleDownShortlistCandidate(
        symbol=_symbol(row),
        trigger_gap_pct=((buy_price - trigger) / trigger) * Decimal("100"),
        buy_price=buy_price,
        trigger_price=trigger,
        lot=_text(row.get("due_lots")),
        due_qty=due_qty,
        integer_qty=integer_qty,
        decimal_left=_decimal_or_none(row.get("decimal_left")),
        active_buy_count=_int_or_zero(row.get("active_buy_count")),
        status="due" if integer_qty is None or integer_qty >= Decimal("1") else "due-fractional",
    )


def _watch_dd_shortlist_candidate(row: dict[str, Any]) -> DoubleDownShortlistCandidate | None:
    buy_price = _decimal_or_none(row.get("buy_price"))
    trigger = _decimal_or_none(row.get("next_trigger"))
    if buy_price is None or trigger is None or trigger <= ZERO:
        return None
    gap = _decimal_or_none(row.get("trigger_gap_pct"))
    if gap is None:
        gap = ((buy_price - trigger) / trigger) * Decimal("100")
    return DoubleDownShortlistCandidate(
        symbol=_symbol(row),
        trigger_gap_pct=gap,
        buy_price=buy_price,
        trigger_price=trigger,
        lot=_text(row.get("next_lot")),
        due_qty=_decimal_or_none(row.get("remaining_lot_shares")),
        integer_qty=None,
        decimal_left=None,
        active_buy_count=_int_or_zero(row.get("active_buy_count")),
        status="watch",
    )


def _keep_best_dd_candidate(
    candidates: dict[str, DoubleDownShortlistCandidate],
    candidate: DoubleDownShortlistCandidate,
) -> None:
    if not candidate.symbol:
        return
    current = candidates.get(candidate.symbol)
    if current is None or (candidate.active_buy_count > 0, candidate.trigger_gap_pct) < (
        current.active_buy_count > 0,
        current.trigger_gap_pct,
    ):
        candidates[candidate.symbol] = candidate


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


def _pct_from_percent(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value.quantize(Decimal('0.0001'))}%"


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(Decimal("0.0001")))


def _num(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _maybe_num(value: Decimal | None) -> str:
    if value is None:
        return ""
    return _num(value)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _int_or_zero(value: Any) -> int:
    try:
        return int(_text(value) or "0")
    except ValueError:
        return 0


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
