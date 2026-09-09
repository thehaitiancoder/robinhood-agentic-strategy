from __future__ import annotations

import tempfile
import unittest
import csv
import json
from decimal import Decimal
from pathlib import Path

from agentic_strategy.daily_summary import (
    SplitAdjustment,
    build_daily_summary,
    read_split_adjustments_csv,
    render_markdown,
    write_daily_summary,
    write_performance_history,
)


class DailySummaryTest(unittest.TestCase):
    def test_builds_paper_pl_hourly_profit_and_sell_cycles(self) -> None:
        summary = build_daily_summary(
            portfolio_payload={
                "portfolio": {
                    "total_value": "1000",
                    "equity_value": "800",
                    "cash": "200",
                    "buying_power": {"buying_power": "250"},
                }
            },
            positions_payload={
                "positions": [
                    {"symbol": "GAIN", "quantity": "10", "average_buy_price": "10"},
                    {"symbol": "LOSS", "quantity": "5", "average_buy_price": "20"},
                    {"symbol": "FLAT", "quantity": "1", "average_buy_price": "5"},
                ],
                "quotes": [
                    {"symbol": "GAIN", "last_non_reg": "12"},
                    {"symbol": "LOSS", "last_trade": "18"},
                    {"symbol": "FLAT", "bid": "5"},
                ],
            },
            orders_payload={
                "orders": [
                    _order("gain-buy", "GAIN", "buy", "10", "10", "2026-06-15T14:00:00Z"),
                    _order("gain-sell", "GAIN", "sell", "4", "12", "2026-06-15T16:30:00Z"),
                    _order("loss-buy", "LOSS", "buy", "2", "20", "2026-06-14T16:00:00Z"),
                    _order("loss-sell", "LOSS", "sell", "1", "18", "2026-06-15T17:05:00Z"),
                ]
            },
            report_date="2026-06-15",
        )

        self.assertEqual(str(summary["paper"].gross_paper_gain), "20")
        self.assertEqual(str(summary["paper"].gross_paper_loss), "-10")
        self.assertEqual(str(summary["paper"].net_paper_gain), "10")

        totals = summary["totals"]
        self.assertEqual(totals["realized_profit"], Decimal("6.00"))
        self.assertEqual(str(totals["sell_proceeds"]), "66")
        self.assertEqual(str(totals["sold_cost_basis"]), "60")
        self.assertEqual(totals["sell_count"], 2)
        self.assertEqual(totals["winning_sells"], 1)
        self.assertEqual(totals["losing_sells"], 1)

        self.assertEqual(summary["hourly"]["09"]["profit"], Decimal("8.00"))
        self.assertEqual(summary["hourly"]["10"]["profit"], Decimal("-2.00"))

        buy_deployment = summary["buy_deployment"]
        self.assertEqual(buy_deployment["filled_buy_count"], 1)
        self.assertEqual(str(buy_deployment["gross_buy_spend"]), "100")
        self.assertEqual(str(buy_deployment["sell_proceeds_offset"]), "66")
        self.assertEqual(str(buy_deployment["net_cash_deployed"]), "34")
        self.assertEqual(str(buy_deployment["hourly"]["07"]["spend"]), "100")
        self.assertEqual(buy_deployment["top_symbols"][0]["symbol"], "GAIN")

        gain_cycle = next(cycle for cycle in summary["cycles"] if cycle.symbol == "GAIN")
        self.assertEqual(str(gain_cycle.weighted_hold_minutes), "150.0")
        self.assertEqual(str(gain_cycle.return_pct), "20.0")
        markdown = render_markdown(summary)
        self.assertIn("FIFO-reconstructed realized P/L", markdown)
        self.assertIn("FIFO rounding adjustment", markdown)
        self.assertNotIn("Broker-authoritative realized P/L", markdown)

    def test_uses_robinhood_realized_pnl_as_authoritative_profit(self) -> None:
        orders = {
            "orders": [
                _order("gain-buy", "GAIN", "buy", "10", "10", "2026-06-15T14:00:00Z"),
                _order("gain-sell", "GAIN", "sell", "4", "12", "2026-06-15T16:30:00Z"),
                _order("loss-buy", "LOSS", "buy", "2", "20", "2026-06-14T16:00:00Z"),
                _order("loss-sell", "LOSS", "sell", "1", "18", "2026-06-15T17:05:00Z"),
            ]
        }
        pnl = {
            "report_date": "2026-06-15",
            "aggregate": {"data": {"total_returns": "5.99"}},
            "trades": [
                {
                    "timestamp": "2026-06-15T16:30:00Z",
                    "symbol": "GAIN",
                    "side": "sell",
                    "quantity": "4",
                    "realized_gain": "7.99",
                },
                {
                    "timestamp": "2026-06-15T17:05:00Z",
                    "symbol": "LOSS",
                    "side": "sell",
                    "quantity": "1",
                    "realized_gain": "-2.00",
                },
            ],
        }

        summary = build_daily_summary(
            portfolio_payload={"portfolio": {}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload=orders,
            realized_pnl_payload=pnl,
            report_date="2026-06-15",
        )

        self.assertEqual(summary["totals"]["realized_profit"], Decimal("5.99"))
        self.assertEqual(summary["totals"]["raw_realized_profit"], Decimal("6"))
        self.assertEqual(summary["totals"]["realized_profit_adjustment"], Decimal("-0.01"))
        self.assertEqual(summary["totals"]["realized_profit_source"], "robinhood_realized_pnl")
        self.assertEqual(summary["hourly"]["09"]["profit"], Decimal("7.99"))
        self.assertEqual(summary["hourly"]["10"]["profit"], Decimal("-2.00"))
        markdown = render_markdown(summary)
        self.assertIn("Broker-authoritative realized P/L", markdown)
        self.assertIn("Broker reconciliation adjustment", markdown)

    def test_rejects_invalid_authoritative_pnl_amounts(self) -> None:
        for field in ("realized_gain", "total_returns"):
            for invalid in (None, "", " ", "NaN", "Infinity", "-Infinity", "invalid"):
                with self.subTest(field=field, value=invalid):
                    pnl = {
                        "report_date": "2026-06-15",
                        "aggregate": {"data": {"total_returns": "0"}},
                        "trades": [{
                            "timestamp": "2026-06-15T16:30:00Z",
                            "symbol": "FLAT",
                            "side": "sell",
                            "quantity": "1",
                            "realized_gain": "0",
                        }],
                    }
                    if field == "total_returns":
                        pnl["aggregate"]["data"][field] = invalid
                    else:
                        pnl["trades"][0][field] = invalid
                    with self.assertRaisesRegex(ValueError, f"{field} must be a finite number"):
                        build_daily_summary(
                            portfolio_payload={},
                            positions_payload={},
                            orders_payload={"orders": [
                                _order("flat-buy", "FLAT", "buy", "1", "10", "2026-06-15T14:00:00Z"),
                                _order("flat-sell", "FLAT", "sell", "1", "10", "2026-06-15T16:30:00Z"),
                            ]},
                            realized_pnl_payload=pnl,
                            report_date="2026-06-15",
                        )

    def test_accepts_zero_authoritative_pnl_amounts(self) -> None:
        for zero in (0, 0.0, "0", "0.00"):
            with self.subTest(value=zero):
                summary = build_daily_summary(
                    portfolio_payload={},
                    positions_payload={},
                    orders_payload={"orders": [
                        _order("flat-buy", "FLAT", "buy", "1", "10", "2026-06-15T14:00:00Z"),
                        _order("flat-sell", "FLAT", "sell", "1", "10", "2026-06-15T16:30:00Z"),
                    ]},
                    realized_pnl_payload={
                        "report_date": "2026-06-15",
                        "aggregate": {"data": {"total_returns": zero}},
                        "trades": [{
                            "timestamp": "2026-06-15T16:30:00Z",
                            "symbol": "FLAT",
                            "side": "sell",
                            "quantity": "1",
                            "realized_gain": zero,
                        }],
                    },
                    report_date="2026-06-15",
                )
                self.assertEqual(summary["totals"]["realized_profit"], Decimal("0"))
                self.assertEqual(summary["totals"]["realized_profit_source"], "robinhood_realized_pnl")

    def test_rejects_incomplete_robinhood_realized_pnl_capture(self) -> None:
        orders = {
            "orders": [
                _order("gain-buy", "GAIN", "buy", "10", "10", "2026-06-15T14:00:00Z"),
                _order("gain-sell", "GAIN", "sell", "4", "12", "2026-06-15T16:30:00Z"),
            ]
        }
        pnl = {
            "report_date": "2026-06-15",
            "aggregate": {"data": {"total_returns": "8.00"}},
            "trades": [],
        }

        with self.assertRaisesRegex(ValueError, "could not be matched"):
            build_daily_summary(
                portfolio_payload={"portfolio": {}},
                positions_payload={"positions": [], "quotes": []},
                orders_payload=orders,
                realized_pnl_payload=pnl,
                report_date="2026-06-15",
            )

    def test_includes_broker_only_corporate_action_realization(self) -> None:
        pnl = {
            "report_date": "2026-08-20",
            "aggregate": {
                "data": {
                    "total_returns": "0.01",
                    "data_points": [{"number_of_trades": 1}],
                }
            },
            "trades": [
                {
                    "timestamp": "2026-08-20T20:00:00Z",
                    "symbol": "AACB",
                    "side": "",
                    "quantity": "0.095057",
                    "price": "10.62520382507337702641572951",
                    "realized_gain": "0.01",
                }
            ],
        }

        summary = build_daily_summary(
            portfolio_payload={"portfolio": {}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={
                "orders": [
                    _order(
                        "aacb-buy",
                        "AACB",
                        "buy",
                        "0.095057",
                        "10.52",
                        "2026-06-11T13:30:01Z",
                    )
                ]
            },
            realized_pnl_payload=pnl,
            report_date="2026-08-20",
        )

        self.assertEqual(summary["totals"]["sell_count"], 1)
        self.assertEqual(summary["totals"]["realized_profit"], Decimal("0.01"))
        self.assertEqual(summary["totals"]["uncosted_quantity"], Decimal("0"))
        cycle = summary["cycles"][0]
        self.assertEqual(cycle.symbol, "AACB")
        self.assertTrue(cycle.order_id.startswith("broker-realized:AACB:"))
        self.assertIsNone(cycle.weighted_hold_minutes)
        self.assertEqual(cycle.proceeds, Decimal("1.010000000000000000000000000"))
        self.assertEqual(cycle.cost_basis, Decimal("1.000000000000000000000000000"))

    def test_applies_inlf_reverse_split_to_realized_fifo_cost(self) -> None:
        pre_split_buys = [
            ("old-1", "0.242130", "4.130000"),
            ("old-2", "0.484260", "3.689900"),
            ("old-3", "2.905560", "2.689900"),
            ("old-4", "244.067040", "0.769600"),
            ("old-5", "247.941120", "0.515400"),
            ("old-6", "247.000000", "0.489600"),
            ("old-7", "992.000000", "0.191800"),
            ("old-8", "248.000000", "0.218200"),
            ("old-9", "1984.000000", "0.115100"),
            ("old-10", "3967.000000", "0.069000"),
        ]
        orders = [
            _order(order_id, "INLF", "buy", quantity, price, "2026-06-30T16:00:00Z")
            for order_id, quantity, price in pre_split_buys
        ]
        # Robinhood's displayed realized result uses the broker order average, even when
        # the execution-level price carries finer precision.
        orders[4]["executions"][0]["price"] = "0.51535708"
        orders.extend(
            [
                _order("new-1", "INLF", "buy", "2", "2.225000", "2026-07-21T19:59:47Z"),
                _order("new-2", "INLF", "buy", "1", "3.869900", "2026-07-22T22:35:33Z"),
                _order("new-3", "INLF", "buy", "5", "3.679100", "2026-07-23T19:51:23Z"),
                _order(
                    "inlf-sell",
                    "INLF",
                    "sell",
                    "47.668201",
                    "8.315000",
                    "2026-08-05T15:31:31Z",
                ),
            ]
        )

        summary = build_daily_summary(
            portfolio_payload={"portfolio": {}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": orders},
            report_date="2026-08-05",
            split_adjustments={
                "INLF": (
                    SplitAdjustment(
                        symbol="INLF",
                        effective_date="2026-07-06",
                        split_ratio="1:200",
                        base_order_id="old-1",
                    ),
                )
            },
        )

        self.assertEqual(summary["totals"]["sell_count"], 1)
        self.assertEqual(summary["totals"]["sold_cost_basis"], Decimal("1220.332580950000"))
        self.assertEqual(summary["totals"]["sell_proceeds"], Decimal("396.361091315000"))
        self.assertEqual(summary["totals"]["realized_profit"], Decimal("-823.97"))
        self.assertEqual(
            summary["totals"]["raw_realized_profit"],
            Decimal("-823.971489635000"),
        )
        cycle = summary["cycles"][0]
        self.assertEqual(cycle.broker_display_gain, Decimal("-823.97"))
        self.assertEqual(str(cycle.quantity), "47.668201")
        self.assertEqual(str(cycle.uncosted_quantity), "0")

    def test_applies_gibo_reverse_split_and_sums_broker_display_cents(self) -> None:
        summary = build_daily_summary(
            portfolio_payload={"portfolio": {}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={
                "orders": [
                    _order("old-base", "GIBO", "buy", "0.714336", "1.399900", "2026-06-12T13:30:01Z"),
                    _order("new-buy", "GIBO", "buy", "0.171438", "25.999900", "2026-06-30T19:06:34Z"),
                    _order("gibo-sell", "GIBO", "sell", "0.200011", "30.250000", "2026-08-05T16:41:09Z"),
                ]
            },
            report_date="2026-08-05",
            split_adjustments={
                "GIBO": (
                    SplitAdjustment(
                        symbol="GIBO",
                        effective_date="2026-06-29",
                        split_ratio="1:25",
                        base_order_id="old-base",
                    ),
                )
            },
        )

        cycle = summary["cycles"][0]
        self.assertEqual(cycle.cost_basis, Decimal("5.45735838264400"))
        self.assertEqual(cycle.realized_gain, Decimal("0.59297436735600"))
        self.assertEqual(summary["totals"]["realized_profit"], Decimal("0.59"))
        self.assertEqual(
            summary["totals"]["raw_realized_profit"],
            Decimal("0.59297436735600"),
        )

    def test_reads_expanded_split_adjustment_csv_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "split-adjustments.csv"
            path.write_text(
                "symbol,effective_date,split_ratio,pre_split_base_qty,pre_split_base_price,"
                "adjusted_base_qty,adjusted_base_price,ladder_profile,base_order_id,notes\n"
                "INLF,2026-07-06,1:200,0.242130,4.130000,0.00121065,826.000000,"
                "standard,old-base,verified reverse split\n",
                encoding="utf-8",
            )

            adjustments = read_split_adjustments_csv(path)

        self.assertEqual(len(adjustments["INLF"]), 1)
        adjustment = adjustments["INLF"][0]
        self.assertEqual(adjustment.effective_date, "2026-07-06")
        self.assertEqual(adjustment.quantity_multiplier, Decimal("0.005"))
        self.assertEqual(adjustment.price_multiplier, Decimal("200"))
        self.assertEqual(adjustment.base_order_id, "old-base")

    def test_writes_markdown_json_and_cycle_csv(self) -> None:
        summary = build_daily_summary(
            portfolio_payload={"portfolio": {}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": []},
            report_date="2026-06-15",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_daily_summary(
                summary=summary,
                markdown_output=root / "daily-summary.md",
                cycles_csv=root / "cycles.csv",
                json_output=root / "daily-summary.json",
            )

            markdown = (root / "daily-summary.md").read_text(encoding="utf-8")
            self.assertIn("Paper P/L", markdown)
            self.assertIn("DD Cash Deployment", markdown)
            self.assertIn("order_id", (root / "cycles.csv").read_text(encoding="utf-8"))
            summary_json = (root / "daily-summary.json").read_text(encoding="utf-8")
            self.assertIn('"report_date": "2026-06-15"', summary_json)
            self.assertIn('"buy_deployment"', summary_json)

    def test_updates_performance_history_once_per_report_date(self) -> None:
        first = build_daily_summary(
            portfolio_payload={"portfolio": {"total_value": "1000", "cash": "200", "buying_power": "250"}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": []},
            report_date="2026-06-15",
        )
        second = build_daily_summary(
            portfolio_payload={"portfolio": {"total_value": "1100", "cash": "300", "buying_power": "350"}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": []},
            report_date="2026-06-15",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_csv = root / "performance-history.csv"
            history_md = root / "performance-history.md"

            write_daily_summary(
                summary=first,
                markdown_output=root / "daily-summary.md",
                history_csv=history_csv,
                history_markdown=history_md,
            )
            write_daily_summary(
                summary=second,
                markdown_output=root / "daily-summary.md",
                history_csv=history_csv,
                history_markdown=history_md,
            )

            with history_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["account_value"], "1100")
            markdown = history_md.read_text(encoding="utf-8")
            self.assertIn("Robinhood Strategy Performance History", markdown)
            self.assertIn("2026-06-15", markdown)
            self.assertIn("$1,100.00", markdown)

    def test_performance_history_accepts_saved_summary_json_shape(self) -> None:
        summary = build_daily_summary(
            portfolio_payload={"portfolio": {"total_value": "1000", "cash": "200", "buying_power": "250"}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": []},
            report_date="2026-06-15",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            json_path = root / "daily-summary.json"
            history_csv = root / "performance-history.csv"
            history_md = root / "performance-history.md"
            write_daily_summary(summary=summary, markdown_output=root / "daily-summary.md", json_output=json_path)

            write_performance_history(
                summary=json.loads(json_path.read_text(encoding="utf-8")),
                history_csv=history_csv,
                history_markdown=history_md,
            )

            with history_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(rows[0]["report_date"], "2026-06-15")
            self.assertIn("$1,000.00", history_md.read_text(encoding="utf-8"))

    def test_performance_history_renders_partial_backfill_rows_without_fake_zero_snapshots(self) -> None:
        backfill = {
            "report_date": "2026-06-10",
            "generated_at": "2026-06-26T07:22:05.748726+00:00",
            "portfolio": {
                "total_value": "",
                "equity_value": "",
                "cash": "",
                "buying_power": "",
            },
            "paper": {
                "gross_paper_gain": "",
                "gross_paper_loss": "",
                "net_paper_gain": "",
                "long_market_value": "",
                "positions_up": "",
                "positions_down": "",
                "positions_flat": "",
            },
            "totals": {
                "realized_profit": "0.561059538100",
                "sell_proceeds": "5.560934338100",
                "sold_cost_basis": "4.999874800000",
                "realized_return_pct": "11.22147174765256122013295213",
                "sell_count": 5,
                "costed_sell_count": 5,
                "winning_sells": 5,
                "losing_sells": 0,
                "uncosted_quantity": "0.000000",
                "average_hold_minutes": "107.0148800000000052",
                "median_hold_minutes": "59.09668333333333",
            },
            "hourly": {
                "06": {"count": 2, "proceeds": "2.224450035700", "cost": "1.999874800000", "profit": "0.224575235700"},
                "07": {"count": 2, "proceeds": "2.237792562600", "cost": "1.999874800000", "profit": "0.237917762600"},
                "12": {"count": 1, "proceeds": "1.098691739800", "cost": "1.000125200000", "profit": "0.098566539800"},
            },
            "cycles": [],
        }
        first = build_daily_summary(
            portfolio_payload={"portfolio": {"total_value": "1000", "cash": "200", "buying_power": "250"}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": []},
            report_date="2026-06-15",
        )
        second = build_daily_summary(
            portfolio_payload={"portfolio": {"total_value": "1100", "cash": "300", "buying_power": "350"}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": []},
            report_date="2026-06-16",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_csv = root / "performance-history.csv"
            history_md = root / "performance-history.md"

            write_performance_history(summary=backfill, history_csv=history_csv, history_markdown=history_md)
            write_performance_history(summary=first, history_csv=history_csv, history_markdown=history_md)
            write_performance_history(summary=second, history_csv=history_csv, history_markdown=history_md)

            markdown = history_md.read_text(encoding="utf-8")
            self.assertIn("| 2026-06-10 |  |  |  | $0.56 |  | 5 | 5/0 | 1.8 hr | 59.1 min | 0 |", markdown)
            self.assertIn("| Account value change since first tracked day | $100.00 |", markdown)
            self.assertIn("Blank account snapshot cells indicate realized-only backfill rows", markdown)

    def test_performance_history_reads_utf8_bom_csv(self) -> None:
        summary = build_daily_summary(
            portfolio_payload={"portfolio": {"total_value": "1100", "cash": "300", "buying_power": "350"}},
            positions_payload={"positions": [], "quotes": []},
            orders_payload={"orders": []},
            report_date="2026-06-16",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_csv = root / "performance-history.csv"
            history_md = root / "performance-history.md"
            with history_csv.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "report_date",
                        "generated_at",
                        "account_value",
                        "equity_value",
                        "cash",
                        "buying_power",
                        "long_market_value",
                        "gross_paper_gain",
                        "gross_paper_loss",
                        "net_paper_pl",
                        "positions_up",
                        "positions_down",
                        "positions_flat",
                        "realized_profit",
                        "sell_proceeds",
                        "sold_cost_basis",
                        "realized_return_pct",
                        "sell_count",
                        "costed_sell_count",
                        "winning_sells",
                        "losing_sells",
                        "uncosted_quantity",
                        "average_hold_minutes",
                        "median_hold_minutes",
                        "profit_by_hour",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "report_date": "2026-06-10",
                        "generated_at": "2026-06-26T07:22:05.748726+00:00",
                        "realized_profit": "0.561059538100",
                        "sell_proceeds": "5.560934338100",
                        "sold_cost_basis": "4.999874800000",
                        "realized_return_pct": "11.22147174765256122013295213",
                        "sell_count": "5",
                        "costed_sell_count": "5",
                        "winning_sells": "5",
                        "losing_sells": "0",
                        "uncosted_quantity": "0.000000",
                        "average_hold_minutes": "107.0148800000000052",
                        "median_hold_minutes": "59.09668333333333",
                        "profit_by_hour": "06=0.224575235700;07=0.237917762600;12=0.098566539800",
                    }
                )

            write_performance_history(summary=summary, history_csv=history_csv, history_markdown=history_md)

            with history_csv.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual([row["report_date"] for row in rows], ["2026-06-10", "2026-06-16"])


def _order(order_id: str, symbol: str, side: str, quantity: str, price: str, timestamp: str) -> dict[str, object]:
    return {
        "id": order_id,
        "symbol": symbol,
        "side": side,
        "state": "filled",
        "quantity": quantity,
        "cumulative_quantity": quantity,
        "average_price": price,
        "last_transaction_at": timestamp,
        "executions": [
            {
                "quantity": quantity,
                "price": price,
                "timestamp": timestamp,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
