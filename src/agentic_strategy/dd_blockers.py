from __future__ import annotations

from csv import DictReader, DictWriter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final


DEFAULT_KNOWN_DD_BLOCKERS_CSV = Path("data/runtime/dd-known-blockers.csv")

KNOWN_DD_BLOCKER_FIELDS: Final = [
    "symbol",
    "blocker_type",
    "status",
    "reason",
    "first_seen_at",
    "last_seen_at",
    "last_reported_at",
    "seen_count",
    "report_count",
    "signature",
    "quantity",
    "buy_price",
    "deepest_trigger",
    "due_qty",
    "integer_qty",
    "active_buy_count",
    "source",
    "notes",
]


@dataclass(frozen=True)
class DDBlockerEvent:
    symbol: str
    blocker_type: str
    status: str
    reason: str
    quantity: str = ""
    buy_price: str = ""
    deepest_trigger: str = ""
    due_qty: str = ""
    integer_qty: str = ""
    active_buy_count: str = ""
    source: str = ""
    notes: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.symbol.upper(), self.blocker_type)

    @property
    def signature(self) -> str:
        return "|".join(
            [
                self.reason,
                self.quantity,
                self.buy_price,
                self.deepest_trigger,
                self.due_qty,
                self.integer_qty,
                self.active_buy_count,
                self.notes,
            ]
        )


@dataclass(frozen=True)
class DDBlockerCacheUpdate:
    reported: list[dict[str, str]]
    suppressed: list[dict[str, str]]
    cache_rows: list[dict[str, str]]


def update_known_dd_blockers(
    path: Path,
    events: list[DDBlockerEvent],
    *,
    recorded_at: datetime,
) -> DDBlockerCacheUpdate:
    if not events:
        return DDBlockerCacheUpdate(reported=[], suppressed=[], cache_rows=_read_rows(path))

    existing_rows = _read_rows(path)
    rows_by_key = {(_row_symbol(row), row.get("blocker_type", "")): row for row in existing_rows}
    reported: list[dict[str, str]] = []
    suppressed: list[dict[str, str]] = []
    now_text = recorded_at.isoformat()

    for event in events:
        existing = rows_by_key.get(event.key)
        unchanged = existing is not None and existing.get("signature") == event.signature
        row = _row_from_event(
            event,
            existing=existing,
            now_text=now_text,
            unchanged=unchanged,
        )
        rows_by_key[event.key] = row
        if unchanged:
            suppressed.append(row)
        else:
            reported.append(row)

    rows = sorted(rows_by_key.values(), key=lambda item: (_row_symbol(item), item.get("blocker_type", "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = DictWriter(handle, fieldnames=KNOWN_DD_BLOCKER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return DDBlockerCacheUpdate(reported=reported, suppressed=suppressed, cache_rows=rows)


def _row_from_event(
    event: DDBlockerEvent,
    *,
    existing: dict[str, str] | None,
    now_text: str,
    unchanged: bool,
) -> dict[str, str]:
    first_seen = existing.get("first_seen_at", now_text) if existing else now_text
    seen_count = _int_text(existing.get("seen_count", "0") if existing else "0")
    report_count = _int_text(existing.get("report_count", "0") if existing else "0")
    last_reported = existing.get("last_reported_at", "") if existing else ""
    if not unchanged:
        report_count += 1
        last_reported = now_text
    return {
        "symbol": event.symbol.upper(),
        "blocker_type": event.blocker_type,
        "status": event.status,
        "reason": event.reason,
        "first_seen_at": first_seen,
        "last_seen_at": now_text,
        "last_reported_at": last_reported,
        "seen_count": str(seen_count + 1),
        "report_count": str(report_count),
        "signature": event.signature,
        "quantity": event.quantity,
        "buy_price": event.buy_price,
        "deepest_trigger": event.deepest_trigger,
        "due_qty": event.due_qty,
        "integer_qty": event.integer_qty,
        "active_buy_count": event.active_buy_count,
        "source": event.source,
        "notes": event.notes,
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [{field: row.get(field, "") for field in KNOWN_DD_BLOCKER_FIELDS} for row in DictReader(handle)]


def _row_symbol(row: dict[str, str]) -> str:
    return row.get("symbol", "").upper()


def _int_text(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
