from __future__ import annotations

import unittest
from decimal import Decimal

from agentic_strategy import (
    UNDER5_20_LADDER_PROFILE,
    build_ladder,
    combined_due_lot_shares,
    drop_pct_for_next_lot,
    due_double_down_lots,
    integer_part_quantity,
    ladder_profile_for_entry_price,
    ladder_profile_for_open_lot_count,
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

    def test_under5_profile_uses_ref2023_drops(self) -> None:
        self.assertEqual(ladder_profile_for_entry_price(Decimal("4.99")), UNDER5_20_LADDER_PROFILE)
        self.assertEqual(ladder_profile_for_entry_price(Decimal("5.00")), "standard")
        self.assertEqual(
            ladder_profile_for_open_lot_count(Decimal("4.99"), 1),
            UNDER5_20_LADDER_PROFILE,
        )
        self.assertEqual(ladder_profile_for_open_lot_count(Decimal("4.99"), 2), "standard")
        self.assertEqual(
            [drop_pct_for_next_lot(index, ladder_profile=UNDER5_20_LADDER_PROFILE) for index in range(2, 12)],
            [Decimal("0.20")] * 10,
        )
        self.assertEqual(drop_pct_for_next_lot(12, ladder_profile=UNDER5_20_LADDER_PROFILE), Decimal("0.40"))

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
        self.assertEqual({lot.ladder_profile for lot in lots}, {"standard"})

    def test_under5_ladder_prices(self) -> None:
        lots = build_ladder(entry_price=Decimal("4.00"), base_usd=Decimal("1"), through_lot_index=4)

        self.assertEqual([lot.trigger_price for lot in lots], [
            Decimal("4.00"),
            Decimal("3.2000"),
            Decimal("2.560000"),
            Decimal("2.04800000"),
        ])
        self.assertEqual([lot.drop_pct for lot in lots], [
            Decimal("0"),
            Decimal("0.20"),
            Decimal("0.20"),
            Decimal("0.20"),
        ])
        self.assertEqual({lot.ladder_profile for lot in lots}, {UNDER5_20_LADDER_PROFILE})

    def test_sub_dollar_ladder_uses_whole_shares(self) -> None:
        lots = build_ladder(entry_price=Decimal("0.50"), base_usd=Decimal("1"), through_lot_index=4)

        self.assertEqual([lot.lot_shares for lot in lots], [
            Decimal("2"),
            Decimal("4"),
            Decimal("8"),
            Decimal("16"),
        ])
        self.assertEqual({lot.sizing_mode for lot in lots}, {"whole_share_quantity"})
        self.assertEqual({lot.ladder_profile for lot in lots}, {UNDER5_20_LADDER_PROFILE})

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

    def test_combines_due_lots_with_under5_profile(self) -> None:
        lots = due_double_down_lots(
            current_lot_index=1,
            next_trigger=Decimal("3.2000"),
            next_shares=Decimal("0.50"),
            buy_price=Decimal("2.50"),
            ladder_profile=UNDER5_20_LADDER_PROFILE,
        )

        self.assertEqual([lot.lot_index for lot in lots], [2, 3])
        self.assertEqual([lot.trigger_price for lot in lots], [
            Decimal("3.2000"),
            Decimal("2.560000"),
        ])
        self.assertEqual(combined_due_lot_shares(lots), Decimal("1.50"))

    def test_integer_part_quantity_floors_fractional_quantity(self) -> None:
        self.assertEqual(integer_part_quantity(Decimal("18.190084")), Decimal("18"))
        self.assertEqual(integer_part_quantity(Decimal("2.000000")), Decimal("2"))


if __name__ == "__main__":
    unittest.main()
