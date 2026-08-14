import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from tools import wp04_backfill_core as core


ROOT = Path(__file__).resolve().parents[3]
ASSET_SET = ROOT / "config" / "wp04_shadow_assets.v1.json"
ENTRYPOINT = ROOT / "tools" / "wp04_shadow_backfill.py"
UTC = dt.timezone.utc


class Wp04BackfillTests(unittest.TestCase):
    def test_repository_asset_set_is_versioned_and_reconciled(self):
        version, assets, checksum = core.load_asset_set(ASSET_SET)
        self.assertEqual("wp04-shadow-assets-2026-08-v1", version)
        self.assertEqual(8, len(assets))
        self.assertRegex(checksum, r"^[0-9a-f]{64}$")
        stocks = [row for row in assets if row["asset_type"] == "STOCK"]
        self.assertTrue(all(row["stooq_symbol"] for row in stocks))
        self.assertEqual(
            {"BTC-USD", "ETH-USD"},
            {row["ticker"] for row in assets if row["asset_type"] == "CRYPTO"},
        )
        self.assertEqual(
            {"CLP=X"},
            {row["ticker"] for row in assets if row["asset_type"] == "FX"},
        )

    def test_date_ranges_are_bounded(self):
        core.validate_date_ranges(
            start_date=dt.date(2022, 1, 1),
            end_date=dt.date(2026, 8, 13),
            intraday_start_date=dt.date(2026, 6, 16),
            hourly_start_date=dt.date(2025, 1, 1),
        )
        with self.assertRaisesRegex(core.Wp04BackfillError, "intraday range"):
            core.validate_date_ranges(
                start_date=dt.date(2022, 1, 1),
                end_date=dt.date(2026, 8, 13),
                intraday_start_date=dt.date(2026, 1, 1),
                hourly_start_date=dt.date(2025, 1, 1),
            )

    def test_calendar_rows_cover_xnys_crypto_and_fx(self):
        _version, assets, _checksum = core.load_asset_set(ASSET_SET)
        rows = core.calendar_rows(
            assets,
            start_date=dt.date(2026, 3, 6),
            end_date=dt.date(2026, 3, 9),
            available_at=dt.datetime(2026, 8, 14, tzinfo=UTC),
        )
        exchanges = {row["exchange"] for row in rows}
        self.assertEqual({"XNYS", "CRYPTO_24_7", "FX_24_5"}, exchanges)
        xnys = [row for row in rows if row["exchange"] == "XNYS"]
        self.assertEqual(2, len(xnys))
        self.assertNotEqual(xnys[0]["open_utc"].hour, xnys[1]["open_utc"].hour)
        self.assertTrue(all(row["expected_15m_bars"] == 26 for row in xnys))
        crypto = [row for row in rows if row["exchange"] == "CRYPTO_24_7"]
        self.assertEqual(4, len(crypto))
        self.assertTrue(all(row["expected_1h_bars"] == 24 for row in crypto))

    def test_plan_checksum_covers_files_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = core.write_jsonl(
                root / "prices.jsonl",
                [{"raw_revision_id": "r1", "value": 1}],
            )
            plan = core.finalize_plan(
                {
                    "schema_version": 1,
                    "operation": "WP04_SHADOW_BACKFILL",
                    "git_sha": "a" * 40,
                    "asset_set_version": "v1",
                    "asset_set_sha256": "b" * 64,
                    "assets": [{"ticker": "AAPL"}],
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-02",
                    "intraday_start_date": "2026-01-01",
                    "hourly_start_date": "2026-01-01",
                    "files": {"market_price_raw": first},
                    "total_row_count": 1,
                    "max_rows": 10,
                    "provider_versions": {"YAHOO": "test"},
                    "production_change_allowed": False,
                }
            )
            core.verify_plan_checksum(plan, plan["plan_checksum"])
            core.verify_plan_files(plan)
            changed = dict(plan)
            changed["assets"] = [{"ticker": "MSFT"}]
            with self.assertRaisesRegex(core.Wp04BackfillError, "checksum mismatch"):
                core.verify_plan_checksum(changed, plan["plan_checksum"])

    def test_entrypoint_has_no_deploy_or_broker_surface(self):
        source = ENTRYPOINT.read_text(encoding="utf-8").lower()
        for forbidden in (
            "gcloud run deploy",
            "terraform apply",
            "scheduler jobs",
            "submit_order",
            "alpaca",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("wp04_shadow_write", source)
        self.assertIn("when not matched then", source)
        self.assertNotIn("when matched then", source)


if __name__ == "__main__":
    unittest.main()
