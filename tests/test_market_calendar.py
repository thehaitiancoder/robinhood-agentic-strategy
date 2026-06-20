from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agentic_strategy.market_calendar import (
    calendar_status_payload,
    format_status_line,
    read_market_holidays_csv,
    resolve_lookup_date,
)


class MarketCalendarTest(unittest.TestCase):
    def test_closed_holiday_is_reported(self) -> None:
        payload = calendar_status_payload("2026-06-19", calendar_path="config/market-holidays.csv")

        self.assertEqual(payload["market_status"], "closed")
        self.assertEqual(payload["date"], "2026-06-19")
        self.assertIn("Juneteenth", payload["description"])

    def test_open_day_is_reported_when_no_calendar_row_matches(self) -> None:
        payload = calendar_status_payload("2026-06-22", calendar_path="config/market-holidays.csv")

        self.assertEqual(payload["market_status"], "open")
        self.assertEqual(payload["date"], "2026-06-22")
        self.assertEqual(payload["calendar_missing"], "false")

    def test_early_close_has_pacific_close_time(self) -> None:
        payload = calendar_status_payload("2026-11-27", calendar_path="config/market-holidays.csv")

        self.assertEqual(payload["market_status"], "early_close")
        self.assertEqual(payload["close_time_et"], "13:00")
        self.assertEqual(payload["close_time_pt"], "10:00")

    def test_missing_calendar_reports_open_with_missing_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.csv"
            payload = calendar_status_payload("2026-06-19", calendar_path=path)

        self.assertEqual(payload["market_status"], "open")
        self.assertEqual(payload["calendar_missing"], "true")

    def test_today_uses_pacific_date(self) -> None:
        now = datetime(2026, 6, 20, 1, 30, tzinfo=timezone.utc)

        self.assertEqual(resolve_lookup_date("today", now=now).isoformat(), "2026-06-19")

    def test_status_line_quotes_values_with_spaces(self) -> None:
        payload = calendar_status_payload("2026-06-19", calendar_path="config/market-holidays.csv")
        line = format_status_line(payload)

        self.assertIn('market_status=closed', line)
        self.assertIn('description="Juneteenth National Independence Day"', line)

    def test_csv_loads_all_configured_entries(self) -> None:
        entries = read_market_holidays_csv("config/market-holidays.csv")

        self.assertGreaterEqual(len(entries), 30)


if __name__ == "__main__":
    unittest.main()
