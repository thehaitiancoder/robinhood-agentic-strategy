from __future__ import annotations

import unittest

from agentic_strategy.universe import UniverseRecord, merge_universe_records, normalize_symbol


class UniverseRegistryTest(unittest.TestCase):
    def test_normalizes_symbol(self) -> None:
        self.assertEqual(normalize_symbol(" aapl "), "AAPL")

    def test_adds_robinhood_validated_symbol(self) -> None:
        records = merge_universe_records(
            existing=[],
            validations=[
                UniverseRecord(
                    symbol="aapl",
                    name="Apple Inc.",
                    tradable=True,
                    fractional_eligible=True,
                    active=True,
                    updated_at="2026-06-09",
                )
            ],
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].symbol, "AAPL")
        self.assertTrue(records[0].tradable)
        self.assertTrue(records[0].active)

    def test_validation_marks_existing_symbol_inactive(self) -> None:
        records = merge_universe_records(
            existing=[
                UniverseRecord(
                    symbol="OLD",
                    name="Old Co.",
                    tradable=True,
                    fractional_eligible=True,
                    active=True,
                    source="robinhood_validated",
                    updated_at="2026-06-01",
                )
            ],
            validations=[
                UniverseRecord(
                    symbol="old",
                    tradable=False,
                    fractional_eligible=False,
                    active=False,
                    updated_at="2026-06-09",
                )
            ],
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].symbol, "OLD")
        self.assertEqual(records[0].name, "Old Co.")
        self.assertFalse(records[0].tradable)
        self.assertFalse(records[0].active)
        self.assertEqual(records[0].updated_at, "2026-06-09")

    def test_merges_sorted_unique_records(self) -> None:
        records = merge_universe_records(
            existing=[UniverseRecord(symbol="TSLA", tradable=True, active=True)],
            validations=[
                UniverseRecord(symbol="AAPL", tradable=True, active=True),
                UniverseRecord(symbol="tsla", tradable=True, active=True, updated_at="2026-06-09"),
            ],
        )

        self.assertEqual([record.symbol for record in records], ["AAPL", "TSLA"])
        self.assertEqual(records[1].updated_at, "2026-06-09")


if __name__ == "__main__":
    unittest.main()
