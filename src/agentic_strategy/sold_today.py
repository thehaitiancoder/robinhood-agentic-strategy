from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_SOLD_TODAY_MD = Path("data/private/sold-today.md")


@dataclass(frozen=True)
class SoldTodayEntry:
    symbol: str
    sold_time: str
    sold_date: str = ""
    sell_order_id: str = ""
    reason_reopen_blocked: str = ""
    attempt_count: int = 0
    last_attempt_at: str = ""


@dataclass(frozen=True)
class SoldTodayDocument:
    trading_date: str
    entries: tuple[SoldTodayEntry, ...]


def reset_sold_today(
    *,
    output: str | Path = DEFAULT_SOLD_TODAY_MD,
    trading_date: str | None = None,
) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    date = trading_date or _today_pt()
    document = read_sold_today(path) if path.exists() else SoldTodayDocument(date, ())
    _write_document(path, SoldTodayDocument(trading_date=date, entries=document.entries))
    return path


def record_sold_symbols(
    symbols: list[str] | tuple[str, ...],
    *,
    output: str | Path = DEFAULT_SOLD_TODAY_MD,
    sold_at: datetime | None = None,
    trading_date: str | None = None,
    sell_order_id: str = "",
    reason_reopen_blocked: str = "",
) -> Path:
    if not symbols:
        raise ValueError("At least one sold symbol is required.")

    timestamp = _as_pt(sold_at or datetime.now(timezone.utc))
    date = trading_date or timestamp.date().isoformat()
    path = Path(output)
    document = read_sold_today(path) if path.exists() else SoldTodayDocument(date, ())

    sold_time = timestamp.strftime("%H:%M PT")
    sold_symbols = {_normalize_symbol(symbol) for symbol in symbols}
    entries = [entry for entry in document.entries if entry.symbol not in sold_symbols]
    entries.extend(
        SoldTodayEntry(
            symbol=symbol,
            sold_date=date,
            sold_time=sold_time,
            sell_order_id=sell_order_id,
            reason_reopen_blocked=reason_reopen_blocked,
        )
        for symbol in sorted(sold_symbols)
    )

    _write_document(path, SoldTodayDocument(trading_date=date, entries=tuple(entries)))
    return path


def mark_reopened_symbols(
    symbols: list[str] | tuple[str, ...],
    *,
    output: str | Path = DEFAULT_SOLD_TODAY_MD,
    trading_date: str | None = None,
) -> Path:
    if not symbols:
        raise ValueError("At least one reopened symbol is required.")

    date = trading_date or _today_pt()
    path = Path(output)
    document = read_sold_today(path) if path.exists() else SoldTodayDocument(date, ())

    reopened_symbols = {_normalize_symbol(symbol) for symbol in symbols}
    entries = tuple(entry for entry in document.entries if entry.symbol not in reopened_symbols)
    _write_document(path, SoldTodayDocument(trading_date=date, entries=entries))
    return path


def _write_document(path: Path, document: SoldTodayDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_sold_today(document), encoding="utf-8")


def read_sold_today(path: str | Path = DEFAULT_SOLD_TODAY_MD) -> SoldTodayDocument:
    text = Path(path).read_text(encoding="utf-8")
    trading_date = ""
    entries: list[SoldTodayEntry] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("Date:"):
            trading_date = line.removeprefix("Date:").strip().removesuffix(" PT").strip()
            continue
        if line.startswith("Updated:"):
            trading_date = line.removeprefix("Updated:").strip().removesuffix(" PT").strip()
            continue
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            cells = [_unescape_md_cell(cell.strip()) for cell in line.strip("|").split("|")]
            if not cells or cells[0].startswith("---") or "Symbol" in cells[:3]:
                continue
            if len(cells) >= 7:
                entries.append(
                    SoldTodayEntry(
                        sold_date=cells[0],
                        sold_time=cells[1],
                        symbol=_normalize_symbol(cells[2]),
                        sell_order_id=cells[3],
                        reason_reopen_blocked=cells[4],
                        attempt_count=_parse_attempt_count(cells[5]),
                        last_attempt_at=cells[6],
                    )
                )
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "PT":
            entries.append(
                SoldTodayEntry(
                    symbol=_normalize_symbol(parts[2]),
                    sold_date=trading_date,
                    sold_time=f"{parts[0]} PT",
                )
            )

    return SoldTodayDocument(trading_date=trading_date, entries=tuple(entries))


def render_sold_today(document: SoldTodayDocument) -> str:
    lines = [
        "# Pending Reopen Queue",
        f"Updated: {document.trading_date} PT",
        "",
        "| Sold Date | Sold Time | Symbol | Sell Order ID | Reason Reopen Blocked | Attempt Count | Last Attempt At |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    lines.extend(_render_entry(entry) for entry in document.entries)
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize or update the ignored durable pending-reopen queue."
    )
    parser.add_argument("--output", default=str(DEFAULT_SOLD_TODAY_MD))
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Initialize or re-render the queue for the current Pacific date without clearing pending entries.",
    )
    parser.add_argument("--symbol", action="append", default=[], help="Filled sell symbol to mark pending reopen.")
    parser.add_argument(
        "--reopened-symbol",
        action="append",
        default=[],
        help="Filled reopen buy symbol to remove from the pending list.",
    )
    parser.add_argument("--sell-order-id", default="", help="Filled sell order id to store with new pending entries.")
    parser.add_argument(
        "--reason-reopen-blocked",
        default="",
        help="Why the immediate or later reopen is still pending.",
    )
    parser.add_argument("--sold-at", help="ISO timestamp for the sell time. Defaults to now in Pacific time.")
    parser.add_argument("--trading-date", help="YYYY-MM-DD Pacific trading date. Defaults from --sold-at or now.")
    args = parser.parse_args()

    sold_at = _parse_timestamp(args.sold_at) if args.sold_at else None
    actions = sum(bool(action) for action in (args.reset, args.symbol, args.reopened_symbol))
    if actions != 1:
        parser.error("Pass exactly one action: --reset, --symbol, or --reopened-symbol.")
    if args.reset:
        print(reset_sold_today(output=args.output, trading_date=args.trading_date))
        return 0
    if args.symbol:
        print(
            record_sold_symbols(
                args.symbol,
                output=args.output,
                sold_at=sold_at,
                trading_date=args.trading_date,
                sell_order_id=args.sell_order_id,
                reason_reopen_blocked=args.reason_reopen_blocked,
            )
        )
        return 0
    if args.reopened_symbol:
        print(
            mark_reopened_symbols(
                args.reopened_symbol,
                output=args.output,
                trading_date=args.trading_date,
            )
        )
        return 0

    parser.error("Pass --reset, at least one --symbol, or at least one --reopened-symbol.")
    return 2


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed


def _as_pt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    utc_value = value.astimezone(timezone.utc)
    offset = _pacific_utc_offset(utc_value)
    return (utc_value + offset).replace(tzinfo=None)


def _today_pt() -> str:
    return _as_pt(datetime.now(timezone.utc)).date().isoformat()


def _pacific_utc_offset(utc_value: datetime) -> timedelta:
    if _pacific_is_dst(utc_value):
        return timedelta(hours=-7)
    return timedelta(hours=-8)


def _pacific_is_dst(utc_value: datetime) -> bool:
    year = utc_value.year
    return _dst_start_utc(year) <= utc_value.replace(tzinfo=timezone.utc) < _dst_end_utc(year)


def _dst_start_utc(year: int) -> datetime:
    # US Pacific daylight time starts at 2:00 AM local standard time.
    return datetime(year, 3, _nth_weekday_of_month(year, 3, 6, 2), 10, tzinfo=timezone.utc)


def _dst_end_utc(year: int) -> datetime:
    # US Pacific daylight time ends at 2:00 AM local daylight time.
    return datetime(year, 11, _nth_weekday_of_month(year, 11, 6, 1), 9, tzinfo=timezone.utc)


def _nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> int:
    first = datetime(year, month, 1)
    days_until_weekday = (weekday - first.weekday()) % 7
    return 1 + days_until_weekday + ((occurrence - 1) * 7)


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("Sold symbol cannot be blank.")
    return normalized


def _render_entry(entry: SoldTodayEntry) -> str:
    return " | ".join(
        [
            f"| {_escape_md_cell(entry.sold_date)}",
            _escape_md_cell(entry.sold_time),
            _escape_md_cell(entry.symbol),
            _escape_md_cell(entry.sell_order_id),
            _escape_md_cell(entry.reason_reopen_blocked),
            str(entry.attempt_count),
            f"{_escape_md_cell(entry.last_attempt_at)} |",
        ]
    )


def _escape_md_cell(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("|", "\\|")


def _unescape_md_cell(value: str) -> str:
    return value.replace("\\|", "|").replace("\\\\", "\\")


def _parse_attempt_count(value: str) -> int:
    try:
        return int(value or "0")
    except ValueError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
