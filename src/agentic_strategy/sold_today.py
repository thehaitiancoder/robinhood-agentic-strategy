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
    path.write_text(
        render_sold_today(
            SoldTodayDocument(
                trading_date=trading_date or _today_pt(),
                entries=(),
            )
        ),
        encoding="utf-8",
    )
    return path


def record_sold_symbols(
    symbols: list[str] | tuple[str, ...],
    *,
    output: str | Path = DEFAULT_SOLD_TODAY_MD,
    sold_at: datetime | None = None,
    trading_date: str | None = None,
) -> Path:
    if not symbols:
        raise ValueError("At least one sold symbol is required.")

    timestamp = _as_pt(sold_at or datetime.now(timezone.utc))
    date = trading_date or timestamp.date().isoformat()
    path = Path(output)
    document = read_sold_today(path) if path.exists() else SoldTodayDocument(date, ())
    if document.trading_date != date:
        document = SoldTodayDocument(date, ())

    sold_time = timestamp.strftime("%H:%M PT")
    sold_symbols = {_normalize_symbol(symbol) for symbol in symbols}
    entries = [entry for entry in document.entries if entry.symbol not in sold_symbols]
    entries.extend(SoldTodayEntry(symbol=symbol, sold_time=sold_time) for symbol in sorted(sold_symbols))

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
    if document.trading_date != date:
        document = SoldTodayDocument(date, ())

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
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "PT":
            entries.append(SoldTodayEntry(symbol=_normalize_symbol(parts[2]), sold_time=f"{parts[0]} PT"))

    return SoldTodayDocument(trading_date=trading_date, entries=tuple(entries))


def render_sold_today(document: SoldTodayDocument) -> str:
    lines = [
        "# Sold Today Pending Reopen",
        f"Date: {document.trading_date} PT",
        "",
    ]
    lines.extend(f"{entry.sold_time} {entry.symbol}" for entry in document.entries)
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset or update the ignored daily sold-and-not-reopened queue."
    )
    parser.add_argument("--output", default=str(DEFAULT_SOLD_TODAY_MD))
    parser.add_argument("--reset", action="store_true", help="Clear the list for the current Pacific trading date.")
    parser.add_argument("--symbol", action="append", default=[], help="Filled sell symbol to mark pending reopen.")
    parser.add_argument(
        "--reopened-symbol",
        action="append",
        default=[],
        help="Filled reopen buy symbol to remove from the pending list.",
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


if __name__ == "__main__":
    raise SystemExit(main())
