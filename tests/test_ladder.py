from __future__ import annotations

import unittest
from decimal import Decimal

from agentic_strategy import (
    build_ladder,
    combined_due_lot_shares,
    drop_pct_for_next_lot,
    due_double_down_lots,
    integer_part_quantity,
    lot_shares_for_target,
    sizing_mode_for_price,
)


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
        self.assertEqual({lot.sizing_mode for lot in lots}, {"dollar_fractional"})

    def test_sub_dollar_ladder_uses_whole_shares(self) -> None:
        lots = build_ladder(entry_price=Decimal("0.50"), base_usd=Decimal("1"), through_lot_index=4)

        self.assertEqual([lot.lot_shares for lot in lots], [
            Decimal("2"),
            Decimal("4"),
            Decimal("8"),
            Decimal("16"),
        ])
        self.assertEqual({lot.sizing_mode for lot in lots}, {"whole_share_quantity"})

    def test_sub_dollar_target_shares_do_not_exceed_target_notional(self) -> None:
        self.assertEqual(lot_shares_for_target(Decimal("0.75"), Decimal("1")), Decimal("1"))
        self.assertEqual(lot_shares_for_target(Decimal("0.50"), Decimal("1")), Decimal("2"))
        self.assertEqual(sizing_mode_for_price(Decimal("0.99")), "whole_share_quantity")
        self.assertEqual(sizing_mode_for_price(Decimal("1.00")), "dollar_fractional")

    def test_combines_all_due_double_down_lots(self) -> None:
        lots = due_double_down_lots(
            current_lot_index=1,
            next_trigger=Decimal("90.00"),
            next_shares=Decimal("0.02"),
            buy_price=Decimal("70.00"),
        )

        self.assertEqual([lot.lot_index for lot in lots], [2, 3, 4])
        self.assertEqual([lot.trigger_price for lot in lots], [
            Decimal("90.00"),
            Decimal("81.0000"),
            Decimal("72.900000"),
        ])
        self.assertEqual(combined_due_lot_shares(lots), Decimal("0.14"))

    def test_integer_part_quantity_floors_fractional_quantity(self) -> None:
        self.assertEqual(integer_part_quantity(Decimal("18.190084")), Decimal("18"))
        self.assertEqual(integer_part_quantity(Decimal("2.000000")), Decimal("2"))


if __name__ == "__main__":
    unittest.main()
