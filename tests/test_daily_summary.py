from __future__ import annotations

import tempfile
import unittest
import csv
import json
from pathlib import Path

from agentic_strategy.daily_summary import build_daily_summary, write_daily_summary, write_performance_history


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
        self.assertEqual(str(totals["realized_profit"]), "6")
        self.assertEqual(str(totals["sell_proceeds"]), "66")
        self.assertEqual(str(totals["sold_cost_basis"]), "60")
        self.assertEqual(totals["sell_count"], 2)
        self.assertEqual(totals["winning_sells"], 1)
        self.assertEqual(totals["losing_sells"], 1)

        self.assertEqual(str(summary["hourly"]["09"]["profit"]), "8")
        self.assertEqual(str(summary["hourly"]["10"]["profit"]), "-2")

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
