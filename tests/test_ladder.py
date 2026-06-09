from __future__ import annotations

import unittest
from decimal import Decimal

from agentic_strategy import build_ladder, drop_pct_for_next_lot


class LotLadderTest(unittest.TestCase):
    def test_drop_zones(self) -> None:
        self.assertEqual([drop_pct_for_next_lot(index) for index in range(2, 6)], [Decimal("0.10")] * 4)
        self.assertEqual([drop_pct_for_next_lot(index) for index in range(6, 11)], [Decimal("0.20")] * 5)
        self.assertEqual([drop_pct_for_next_lot(index) for index in range(11, 16)], [Decimal("0.40")] * 5)
        self.assertEqual([drop_pct_for_next_lot(index) for index in range(16, 21)], [Decimal("0.80")] * 5)
        self.assertEqual(drop_pct_for_next_lot(25), Decimal("0.80"))

    def test_ladder_prices_and_shares(self) -> None:
        lots = build_ladder(entry_price=Decimal("100"), base_usd=Decimal("1"), through_lot_index=6)

        self.assertEqual([lot.lot_index for lot in lots], [1, 2, 3, 4, 5, 6])
        self.assertEqual([lot.trigger_price for lot in lots], [
            Decimal("100"),
            Decimal("90.00"),
            Decimal("81.0000"),
            Decimal("72.900000"),
            Decimal("65.61000000"),
            Decimal("52.4880000000"),
        ])
        self.assertEqual([lot.lot_shares for lot in lots], [
            Decimal("0.01"),
            Decimal("0.02"),
            Decimal("0.04"),
            Decimal("0.08"),
            Decimal("0.16"),
            Decimal("0.32"),
        ])


if __name__ == "__main__":
    unittest.main()
