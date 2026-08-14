import datetime as dt
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = (
    ROOT
    / "cloud-functions"
    / "daily_stocks"
    / "custom_function"
    / "wp04_ingestion.py"
)
spec = importlib.util.spec_from_file_location("wp04_ingestion", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
UTC = dt.timezone.utc


class FakeActions:
    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        yield from self._rows


class Wp04IngestionTests(unittest.TestCase):
    def base_payload(self):
        return {
            "timestamp": dt.datetime(2026, 8, 13, 13, 30, tzinfo=UTC),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100.5,
            "adjusted_close": 100.25,
            "volume": 1000,
        }

    def normalize(self, payload=None, **overrides):
        params = {
            "provider": "YAHOO",
            "provider_symbol": "AAPL",
            "ticker": "AAPL",
            "asset_type": "STOCK",
            "exchange": "XNYS",
            "source_interval": "15m",
            "source_timezone": "UTC",
            "currency": "USD",
            "ingestion_run_id": "run-a",
            "source_version": "yfinance-test",
            "ingested_at": dt.datetime(
                2026,
                8,
                13,
                13,
                46,
                tzinfo=UTC,
            ),
        }
        params.update(overrides)
        return module.normalize_price_record(
            payload or self.base_payload(),
            **params,
        )

    def test_same_payload_across_runs_is_same_revision(self):
        first = self.normalize(ingestion_run_id="run-a")
        second = self.normalize(ingestion_run_id="run-b")
        self.assertEqual(first["raw_record_id"], second["raw_record_id"])
        self.assertEqual(first["raw_revision_id"], second["raw_revision_id"])

    def test_payload_change_creates_new_revision_not_new_logical_record(self):
        first = self.normalize()
        changed = self.base_payload()
        changed["close"] = 100.75
        second = self.normalize(changed)
        self.assertEqual(first["raw_record_id"], second["raw_record_id"])
        self.assertNotEqual(first["raw_revision_id"], second["raw_revision_id"])

    def test_shadow_destination_gate(self):
        self.assertEqual(
            "stocks-437902.wp04_shadow.market_price_raw",
            module.validate_shadow_table(
                "stocks-437902.wp04_shadow.market_price_raw",
                "shadow",
            ),
        )
        with self.assertRaisesRegex(ValueError, "environment=shadow"):
            module.validate_shadow_table(
                "stocks-437902.wp04_shadow.market_price_raw",
                "production",
            )
        with self.assertRaisesRegex(ValueError, "contain 'shadow'"):
            module.validate_shadow_table(
                "stocks-437902.acciones_dataset.market_price_raw",
                "shadow",
            )

    def test_corporate_action_backfill_is_not_historically_eligible(self):
        actions = FakeActions(
            [
                (
                    dt.datetime(2026, 8, 1, tzinfo=UTC),
                    {"Dividends": 0.25, "Stock Splits": 0},
                ),
                (
                    dt.datetime(2026, 8, 2, tzinfo=UTC),
                    {"Dividends": 0, "Stock Splits": 2},
                ),
            ]
        )
        rows = module.normalize_corporate_actions(
            actions,
            ticker="AAPL",
            provider="YAHOO",
            currency="USD",
            ingestion_run_id="run-a",
            source_version="test",
            ingested_at=dt.datetime(2026, 8, 14, tzinfo=UTC),
        )
        self.assertEqual(
            {"DIVIDEND", "SPLIT"},
            {row["action_type"] for row in rows},
        )
        self.assertTrue(all(not row["backtest_eligible"] for row in rows))
        self.assertTrue(
            all(
                row["quality_status"] == "UNVERIFIED_AVAILABLE_AT"
                for row in rows
            )
        )

    def test_available_before_bar_close_fails_closed(self):
        payload = self.base_payload()
        payload["available_at"] = payload["timestamp"]
        with self.assertRaisesRegex(ValueError, "bar_end"):
            self.normalize(payload)


if __name__ == "__main__":
    unittest.main()
