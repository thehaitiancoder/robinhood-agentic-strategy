from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_MARKET_HOLIDAYS_CSV = Path("config/market-holidays.csv")
DEFAULT_MARKET = "US_EQUITIES"
try:
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
except ZoneInfoNotFoundError:
    PACIFIC_TZ = None
VALID_STATUSES = {"closed", "early_close"}


@dataclass(frozen=True)
class MarketCalendarEntry:
    date: date
    market: str
    status: str
    close_time_et: str = ""
    close_time_pt: str = ""
    description: str = ""
    source: str = ""


def read_market_holidays_csv(path: str | Path = DEFAULT_MARKET_HOLIDAYS_CSV) -> list[MarketCalendarEntry]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []

    entries: list[MarketCalendarEntry] = []
    with csv_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            entry = _entry_from_row(row)
            if entry.market and entry.status:
                entries.append(entry)
    return entries


def market_status_for_date(
    lookup_date: date,
    entries: list[MarketCalendarEntry],
    *,
    market: str = DEFAULT_MARKET,
) -> MarketCalendarEntry | None:
    normalized_market = _text(market).upper()
    for entry in entries:
        if entry.date == lookup_date and entry.market == normalized_market:
            return entry
    return None


def resolve_lookup_date(value: str, *, now: datetime | None = None) -> date:
    text = _text(value).lower()
    if text in {"", "today"}:
        return _pacific_date(now)
    return date.fromisoformat(text)


def calendar_status_payload(
    lookup_date: date | str,
    *,
    calendar_path: str | Path = DEFAULT_MARKET_HOLIDAYS_CSV,
    market: str = DEFAULT_MARKET,
) -> dict[str, str]:
    if isinstance(lookup_date, str):
        lookup_date = resolve_lookup_date(lookup_date)
    csv_path = Path(calendar_path)
    entry = market_status_for_date(lookup_date, read_market_holidays_csv(csv_path), market=market)
    if entry is None:
        return {
            "market_status": "open",
            "date": lookup_date.isoformat(),
            "market": _text(market).upper(),
            "close_time_et": "",
            "close_time_pt": "",
            "description": "",
            "source": "",
            "calendar_missing": _bool_text(not csv_path.exists()),
        }

    return {
        "market_status": entry.status,
        "date": entry.date.isoformat(),
        "market": entry.market,
        "close_time_et": entry.close_time_et,
        "close_time_pt": entry.close_time_pt,
        "description": entry.description,
        "source": entry.source,
        "calendar_missing": "false",
    }


def format_status_line(payload: dict[str, str]) -> str:
    fields = [
        "market_status",
        "date",
        "market",
        "close_time_et",
        "close_time_pt",
        "description",
        "source",
        "calendar_missing",
    ]
    parts = []
    for field in fields:
        value = payload.get(field, "")
        parts.append(f"{field}={_quote_value(value)}")
    return " ".join(parts)


def _entry_from_row(row: dict[str, str]) -> MarketCalendarEntry:
    status = _text(row.get("status")).lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported market calendar status: {status}")
    return MarketCalendarEntry(
        date=date.fromisoformat(_text(row.get("date"))),
        market=_text(row.get("market")).upper(),
        status=status,
        close_time_et=_text(row.get("close_time_et")),
        close_time_pt=_text(row.get("close_time_pt")),
        description=_text(row.get("description")),
        source=_text(row.get("source")),
    )


def _quote_value(value: str) -> str:
    if value == "":
        return '""'
    if any(char.isspace() for char in value):
        return json.dumps(value)
    return value


def _pacific_date(now: datetime | None = None) -> date:
    if PACIFIC_TZ is not None:
        current = now if now is not None else datetime.now(PACIFIC_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=PACIFIC_TZ)
        return current.astimezone(PACIFIC_TZ).date()

    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.date()

    utc_naive = now.astimezone(timezone.utc).replace(tzinfo=None)
    standard_local = utc_naive - timedelta(hours=8)
    if _is_pacific_dst(standard_local):
        return (utc_naive - timedelta(hours=7)).date()
    return standard_local.date()


def _is_pacific_dst(local_datetime: datetime) -> bool:
    year = local_datetime.year
    starts = _nth_weekday_of_month(year, 3, 6, 2).replace(hour=2)
    ends = _nth_weekday_of_month(year, 11, 6, 1).replace(hour=2)
    return starts <= local_datetime < ends


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime:
    first = datetime(year, month, 1)
    days_until_weekday = (weekday - first.weekday()) % 7
    day = 1 + days_until_weekday + ((n - 1) * 7)
    return datetime(year, month, day)


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the configured US equities market calendar.")
    parser.add_argument("--date", default="today", help="Pacific date to inspect, YYYY-MM-DD or today.")
    parser.add_argument("--calendar", default=str(DEFAULT_MARKET_HOLIDAYS_CSV), help="Market holiday CSV path.")
    parser.add_argument("--market", default=DEFAULT_MARKET, help="Market code to inspect.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a key=value line.")
    args = parser.parse_args()

    lookup_date = resolve_lookup_date(args.date)
    payload = calendar_status_payload(lookup_date, calendar_path=args.calendar, market=args.market)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(format_status_line(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
