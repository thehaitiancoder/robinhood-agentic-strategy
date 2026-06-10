from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agentic_strategy.sold_today import (
    SoldTodayDocument,
    SoldTodayEntry,
    mark_reopened_symbols,
    read_sold_today,
    record_sold_symbols,
    render_sold_today,
    reset_sold_today,
)


class SoldTodayTest(unittest.TestCase):
    def test_reset_writes_empty_daily_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sold-today.md"

            reset_sold_today(output=path, trading_date="2026-06-10")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "# Sold Today Pending Reopen\nDate: 2026-06-10 PT\n",
            )

    def test_record_appends_symbols_with_pacific_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sold-today.md"
            sold_at = datetime(2026, 6, 10, 14, 51, tzinfo=timezone.utc)

            record_sold_symbols(["cbrl", "TGTX"], output=path, sold_at=sold_at)

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "# Sold Today Pending Reopen\nDate: 2026-06-10 PT\n\n07:51 PT CBRL\n07:51 PT TGTX\n",
            )

    def test_record_resets_stale_date_before_appending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sold-today.md"
            path.write_text("# Sold Today Pending Reopen\nDate: 2026-06-09 PT\n\n06:45 PT OLD\n", encoding="utf-8")

            record_sold_symbols(
                ["UCTT"],
                output=path,
                sold_at=datetime(2026, 6, 10, 15, 29, tzinfo=timezone.utc),
            )

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "# Sold Today Pending Reopen\nDate: 2026-06-10 PT\n\n08:29 PT UCTT\n",
            )

    def test_record_replaces_existing_pending_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sold-today.md"
            path.write_text(
                "# Sold Today Pending Reopen\nDate: 2026-06-10 PT\n\n06:46 PT CBRL\n",
                encoding="utf-8",
            )

            record_sold_symbols(
                ["CBRL"],
                output=path,
                sold_at=datetime(2026, 6, 10, 15, 1, tzinfo=timezone.utc),
            )

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "# Sold Today Pending Reopen\nDate: 2026-06-10 PT\n\n08:01 PT CBRL\n",
            )

    def test_mark_reopened_removes_pending_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sold-today.md"
            path.write_text(
                "\n".join(
                    [
                        "# Sold Today Pending Reopen",
                        "Date: 2026-06-10 PT",
                        "",
                        "06:46 PT CBRL",
                        "06:51 PT TGTX",
                        "07:29 PT UCTT",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            mark_reopened_symbols(["CBRL", "TGTX"], output=path, trading_date="2026-06-10")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "# Sold Today Pending Reopen\nDate: 2026-06-10 PT\n\n07:29 PT UCTT\n",
            )

    def test_read_round_trips_rendered_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sold-today.md"
            path.write_text(
                render_sold_today(
                    SoldTodayDocument(
                        trading_date="2026-06-10",
                        entries=(
                            SoldTodayEntry(symbol="CBRL", sold_time="06:46 PT"),
                            SoldTodayEntry(symbol="TGTX", sold_time="06:51 PT"),
                        ),
                    )
                ),
                encoding="utf-8",
            )

            document = read_sold_today(path)

            self.assertEqual(document.trading_date, "2026-06-10")
            self.assertEqual(
                document.entries,
                (
                    SoldTodayEntry(symbol="CBRL", sold_time="06:46 PT"),
                    SoldTodayEntry(symbol="TGTX", sold_time="06:51 PT"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
