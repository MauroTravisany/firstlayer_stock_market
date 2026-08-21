import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from tools import wp04_backfill_core as core
from tools import wp04_provider_window as provider

ROOT = Path(__file__).resolve().parents[3]
ASSET_SET = ROOT / "config" / "wp04_shadow_assets.v1.json"
ENTRYPOINT = ROOT / "tools" / "wp04_shadow_backfill.py"
UTC = dt.timezone.utc

class Wp04BackfillTests(unittest.TestCase):
    def test_repository_asset_set_is_versioned_and_source_specific(self):
        version, assets, checksum = core.load_asset_set(ASSET_SET)
        self.assertEqual("wp04-shadow-assets-2026-08-v2", version)
        self.assertEqual(8, len(assets))
        self.assertRegex(checksum, r"^[0-9a-f]{64}$")
        stocks = [row for row in assets if row["asset_type"] == "STOCK"]
        self.assertTrue(all(row["stooq_symbol"] for row in stocks))
        self.assertTrue(all(row["primary_source"] == "YAHOO" for row in stocks))
        self.assertEqual({"BTC-USD", "ETH-USD"}, {row["ticker"] for row in assets if row["asset_type"] == "CRYPTO"})
        fx = [row for row in assets if row["asset_type"] == "FX"]
        self.assertEqual(1, len(fx))
        self.assertEqual("CLP=X", fx[0]["ticker"])
        self.assertEqual("BCCH_BDE", fx[0]["primary_source"])
        self.assertEqual("F073.TCO.PRE.Z.D", fx[0]["bcch_series_id"])
        self.assertIsNone(fx[0]["yahoo_symbol"])
        self.assertEqual("USD", fx[0]["base_currency"])
        self.assertEqual("CLP", fx[0]["quote_currency"])

    def test_asset_set_rejects_mixed_yahoo_and_bcch_fx_configuration(self):
        document = json.loads(ASSET_SET.read_text(encoding="utf-8"))
        fx = next(row for row in document["assets"] if row["ticker"] == "CLP=X")
        fx["yahoo_symbol"] = "CLP=X"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assets.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(core.Wp04BackfillError, "invalid BCCH_BDE"):
                core.load_asset_set(path)

    def test_date_ranges_are_bounded(self):
        core.validate_date_ranges(start_date=dt.date(2022, 1, 1), end_date=dt.date(2026, 8, 13), intraday_start_date=dt.date(2026, 6, 16), hourly_start_date=dt.date(2025, 1, 1))
        with self.assertRaisesRegex(core.Wp04BackfillError, "intraday range"):
            core.validate_date_ranges(start_date=dt.date(2022, 1, 1), end_date=dt.date(2026, 8, 13), intraday_start_date=dt.date(2026, 1, 1), hourly_start_date=dt.date(2025, 1, 1))

    def test_calendar_rows_cover_xnys_crypto_and_fx(self):
        _version, assets, _checksum = core.load_asset_set(ASSET_SET)
        rows = core.calendar_rows(assets, start_date=dt.date(2026, 3, 6), end_date=dt.date(2026, 3, 9), available_at=dt.datetime(2026, 8, 14, tzinfo=UTC))
        self.assertEqual({"XNYS", "CRYPTO_24_7", "FX_24_5"}, {row["exchange"] for row in rows})
        xnys = [row for row in rows if row["exchange"] == "XNYS"]
        self.assertEqual(2, len(xnys))
        self.assertNotEqual(xnys[0]["open_utc"].hour, xnys[1]["open_utc"].hour)
        self.assertTrue(all(row["expected_15m_bars"] == 26 for row in xnys))

    def test_plan_checksum_covers_files_scope_and_provider_policies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = core.write_jsonl(root / "prices.jsonl", [{"raw_revision_id": "r1", "value": 1}])
            window = provider.resolve_provider_window(anchor_at=dt.datetime(2026, 8, 18, 12, tzinfo=UTC))
            plan = core.finalize_plan({"schema_version": 1, "operation": "WP04_SHADOW_BACKFILL", "git_sha": "a" * 40, "asset_set_version": "v1", "asset_set_sha256": "b" * 64, "assets": [{"ticker": "AAPL"}], "start_date": window["start_date"], "end_date": window["end_date"], "intraday_start_date": window["intraday_start_date"], "hourly_start_date": window["hourly_start_date"], "files": {"market_price_raw": first}, "total_row_count": 1, "max_rows": 10, "provider_versions": {"YAHOO": "test"}, "provider_window_policy": window, "provider_window_checksum": window["window_checksum"], "fx_reference_policy": {"policy_version": "v1", "provider": "BCCH_BDE"}, "production_change_allowed": False})
            core.verify_plan_checksum(plan, plan["plan_checksum"])
            core.verify_plan_files(plan)
            changed = dict(plan)
            changed["fx_reference_policy"] = {"policy_version": "v2", "provider": "BCCH_BDE"}
            with self.assertRaisesRegex(core.Wp04BackfillError, "checksum mismatch"):
                core.verify_plan_checksum(changed, plan["plan_checksum"])

    def test_entrypoint_has_no_deploy_or_broker_surface(self):
        source = ENTRYPOINT.read_text(encoding="utf-8").lower()
        for forbidden in ("gcloud run deploy", "terraform apply", "scheduler jobs", "submit_order", "alpaca"):
            self.assertNotIn(forbidden, source)
        self.assertIn("wp04_shadow_write", source)
        self.assertIn("when not matched then", source)
        self.assertNotIn("when matched then", source)

if __name__ == "__main__":
    unittest.main()
