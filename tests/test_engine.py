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
from agentic_strategy.symbol_policy import SymbolPolicy


class StrategyEngineTest(unittest.TestCase):
    def test_default_cash_buffer_is_15_pct(self) -> None:
        self.assertEqual(StrategyConfig().cash_buffer_pct, Decimal("0.15"))

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

        double_down = next(decision for decision in report.decisions if decision.action == "double_down_ready")
        self.assertEqual(double_down.metrics["order_sizing"], "exact_share_quantity")
        self.assertEqual(double_down.metrics["order_quantity"], "2")
        self.assertEqual(
            double_down.metrics["order_amount_source"],
            "estimate_only_do_not_place_dd_by_dollar_amount",
        )

    def test_due_double_down_combines_multiple_due_lots(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[
                PositionSnapshot(
                    symbol="DROP",
                    quantity=Decimal("0.01"),
                    invested_cost=Decimal("1"),
                    current_lot_index=1,
                    next_trigger_price=Decimal("90.00"),
                    next_lot_shares=Decimal("0.02"),
                )
            ],
            quotes=[QuoteSnapshot(symbol="DROP", bid_price=Decimal("69.50"), ask_price=Decimal("70.00"))],
            universe=[],
        )

        double_down = next(decision for decision in report.decisions if decision.action == "double_down_ready")
        self.assertEqual(double_down.metrics["due_lots"], "2,3,4")
        self.assertEqual(double_down.metrics["combined_due_lot_count"], "3")
        self.assertEqual(double_down.metrics["order_quantity"], "0.14")
        self.assertEqual(double_down.metrics["integer_part_quantity"], "0")
        self.assertEqual(
            double_down.metrics["fractional_reject_fallback"],
            "retry_integer_part_when_at_least_1_share",
        )
        self.assertEqual(double_down.metrics["price_guard_trigger"], "72.9000")

    def test_due_double_down_continues_under5_profile(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[
                PositionSnapshot(
                    symbol="PENNY",
                    quantity=Decimal("0.25"),
                    invested_cost=Decimal("1"),
                    current_lot_index=1,
                    next_trigger_price=Decimal("3.2000"),
                    next_lot_shares=Decimal("0.50"),
                    ladder_profile="under5_20",
                )
            ],
            quotes=[QuoteSnapshot(symbol="PENNY", bid_price=Decimal("2.50"), ask_price=Decimal("2.50"))],
            universe=[],
        )

        double_down = next(decision for decision in report.decisions if decision.action == "double_down_ready")
        self.assertEqual(double_down.metrics["ladder_profile"], "under5_20")
        self.assertEqual(double_down.metrics["due_lots"], "2,3")
        self.assertEqual(double_down.metrics["order_quantity"], "1.50")
        self.assertEqual(double_down.metrics["price_guard_trigger"], "2.5600")

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

    def test_emergency_green_sells_rank_by_highest_positive_return(self) -> None:
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
                PositionSnapshot(symbol="LOW", quantity=Decimal("1"), invested_cost=Decimal("10")),
                PositionSnapshot(symbol="HIGH", quantity=Decimal("1"), invested_cost=Decimal("10")),
            ],
            quotes=[
                QuoteSnapshot(symbol="DROP", bid_price=Decimal("7.40"), ask_price=Decimal("7.50")),
                QuoteSnapshot(symbol="LOW", bid_price=Decimal("10.20"), ask_price=Decimal("10.25")),
                QuoteSnapshot(symbol="HIGH", bid_price=Decimal("10.80"), ask_price=Decimal("10.85")),
            ],
            universe=[],
        )

        candidates = [
            decision.symbol
            for decision in report.decisions
            if decision.action == "emergency_green_sell_candidate"
        ]
        self.assertEqual(candidates, ["HIGH", "LOW"])

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

    def test_symbol_policy_blocks_new_open_candidates_only(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[],
            quotes=[
                QuoteSnapshot(symbol="BLOCK", bid_price=Decimal("5"), ask_price=Decimal("5.10")),
                QuoteSnapshot(symbol="OPEN", bid_price=Decimal("5"), ask_price=Decimal("5.10")),
            ],
            universe=[UniverseEntry(symbol="BLOCK"), UniverseEntry(symbol="OPEN")],
            symbol_policies={
                "BLOCK": SymbolPolicy(
                    symbol="BLOCK",
                    policy="no_new_open",
                    allow_open=False,
                    allow_reopen=False,
                )
            },
        )

        candidates = [decision.symbol for decision in report.decisions if decision.action == "new_open_candidate"]
        self.assertEqual(candidates, ["OPEN"])

    def test_symbol_policy_does_not_block_owned_sell_targets(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[PositionSnapshot(symbol="OWNED", quantity=Decimal("1"), invested_cost=Decimal("10"))],
            quotes=[QuoteSnapshot(symbol="OWNED", bid_price=Decimal("11.05"), ask_price=Decimal("11.10"))],
            universe=[UniverseEntry(symbol="OWNED")],
            symbol_policies={
                "OWNED": SymbolPolicy(
                    symbol="OWNED",
                    policy="no_reopen",
                    allow_open=False,
                    allow_reopen=False,
                )
            },
        )

        actions = [decision.action for decision in report.decisions]
        self.assertIn("sell_target", actions)

    def test_symbol_policy_does_not_block_owned_double_downs(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[
                PositionSnapshot(
                    symbol="OWNED",
                    quantity=Decimal("1"),
                    invested_cost=Decimal("10"),
                    next_trigger_price=Decimal("8"),
                    next_lot_shares=Decimal("2"),
                )
            ],
            quotes=[QuoteSnapshot(symbol="OWNED", bid_price=Decimal("7.40"), ask_price=Decimal("7.50"))],
            universe=[UniverseEntry(symbol="OWNED")],
            symbol_policies={
                "OWNED": SymbolPolicy(
                    symbol="OWNED",
                    policy="no_reopen",
                    allow_open=False,
                    allow_reopen=False,
                )
            },
        )

        actions = [decision.action for decision in report.decisions]
        self.assertIn("double_down_ready", actions)

    def test_new_open_allows_sub_dollar_whole_share_without_fractional_eligibility(self) -> None:
        report = evaluate_strategy(
            portfolio=PortfolioSnapshot(total_value=Decimal("1000"), buying_power=Decimal("900")),
            positions=[],
            quotes=[
                QuoteSnapshot(symbol="PENNY", bid_price=Decimal("0.49"), ask_price=Decimal("0.50")),
            ],
            universe=[UniverseEntry(symbol="PENNY", fractional_eligible=False)],
            config=StrategyConfig(),
        )

        candidates = [decision for decision in report.decisions if decision.action == "new_open_candidate"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].symbol, "PENNY")
        self.assertEqual(candidates[0].metrics["sizing_mode"], "whole_share_quantity")
        self.assertEqual(candidates[0].metrics["estimated_quantity"], "2")


if __name__ == "__main__":
    unittest.main()
