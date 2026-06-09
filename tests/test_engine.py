from __future__ import annotations

import unittest
from decimal import Decimal

from agentic_strategy import (
    PortfolioSnapshot,
    PositionSnapshot,
    QuoteSnapshot,
    StrategyConfig,
    evaluate_strategy,
)
from agentic_strategy.models import UniverseEntry


class StrategyEngineTest(unittest.TestCase):
    def test_sell_target_uses_bid_side_return(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[PositionSnapshot(symbol="WIN", quantity=Decimal("1"), invested_cost=Decimal("10"))],
            quotes=[QuoteSnapshot(symbol="WIN", bid_price=Decimal("11.05"), ask_price=Decimal("11.10"))],
            universe=[],
        )

        actions = [decision.action for decision in report.decisions]
        self.assertIn("sell_target", actions)

    def test_due_double_down_pauses_new_openings(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[
                PositionSnapshot(
                    symbol="DROP",
                    quantity=Decimal("1"),
                    invested_cost=Decimal("10"),
                    next_trigger_price=Decimal("8"),
                    next_lot_shares=Decimal("2"),
                )
            ],
            quotes=[
                QuoteSnapshot(symbol="DROP", bid_price=Decimal("7.40"), ask_price=Decimal("7.50")),
                QuoteSnapshot(symbol="NEW", bid_price=Decimal("5"), ask_price=Decimal("5.10")),
            ],
            universe=[UniverseEntry(symbol="NEW")],
        )

        actions = [decision.action for decision in report.decisions]
        self.assertIn("double_down_ready", actions)
        self.assertIn("pause_new_positions", actions)
        self.assertNotIn("new_open_candidate", actions)

    def test_cash_short_double_down_surfaces_green_sells(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("101")),
            positions=[
                PositionSnapshot(
                    symbol="DROP",
                    quantity=Decimal("1"),
                    invested_cost=Decimal("10"),
                    next_trigger_price=Decimal("8"),
                    next_lot_shares=Decimal("2"),
                ),
                PositionSnapshot(symbol="GREEN", quantity=Decimal("1"), invested_cost=Decimal("10")),
            ],
            quotes=[
                QuoteSnapshot(symbol="DROP", bid_price=Decimal("7.40"), ask_price=Decimal("7.50")),
                QuoteSnapshot(symbol="GREEN", bid_price=Decimal("10.50"), ask_price=Decimal("10.60")),
            ],
            universe=[],
        )

        actions = [decision.action for decision in report.decisions]
        self.assertIn("cash_short_double_down", actions)
        self.assertIn("emergency_green_sell_candidate", actions)

    def test_concentration_cap_blocks_double_down(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("100"), buying_power=Decimal("90")),
            positions=[
                PositionSnapshot(
                    symbol="BIG",
                    quantity=Decimal("5"),
                    invested_cost=Decimal("50"),
                    next_trigger_price=Decimal("8"),
                    next_lot_shares=Decimal("2"),
                )
            ],
            quotes=[QuoteSnapshot(symbol="BIG", bid_price=Decimal("7.40"), ask_price=Decimal("7.50"))],
            universe=[],
        )

        actions = [decision.action for decision in report.decisions]
        self.assertIn("block_double_down", actions)

    def test_new_open_allows_high_share_price_when_cash_rules_pass(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[],
            quotes=[
                QuoteSnapshot(symbol="CHEAP", bid_price=Decimal("5"), ask_price=Decimal("5.10")),
                QuoteSnapshot(symbol="HIGH", bid_price=Decimal("50"), ask_price=Decimal("50.10")),
            ],
            universe=[UniverseEntry(symbol="CHEAP"), UniverseEntry(symbol="HIGH")],
            config=StrategyConfig(),
        )

        candidates = [decision.symbol for decision in report.decisions if decision.action == "new_open_candidate"]
        self.assertEqual(candidates, ["CHEAP", "HIGH"])


if __name__ == "__main__":
    unittest.main()
