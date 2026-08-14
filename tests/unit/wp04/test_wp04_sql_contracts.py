from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "dataform" / "definitions"
WORKFLOW = ROOT / "dataform" / "workflow_settings.yaml"

OPERATIONS = {
    "market_price_raw",
    "corporate_actions_pit",
    "market_session_calendar",
}
RELATIONS = {
    "price_source_reconciliation",
    "market_price_canonical",
    "fx_rates_pit",
    "trading_price_features_canonical_shadow",
    "trading_price_features_wp04_shadow",
    "wp04_legacy_vs_canonical_shadow",
    "trading_price_features",
}
ASSERTIONS = {"audit_canonical_prices"}
WP04_ACTIONS = OPERATIONS | RELATIONS | ASSERTIONS


class Wp04SqlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {
            name: (DEFINITIONS / f"{name}.sqlx").read_text(encoding="utf-8")
            for name in WP04_ACTIONS
        }

    def test_required_action_inventory_and_native_types(self):
        self.assertEqual(11, len(WP04_ACTIONS))
        for name in OPERATIONS:
            self.assertRegex(self.sources[name], r'type:\s*"operations"')
        for name in RELATIONS:
            self.assertRegex(self.sources[name], r'type:\s*"table"')
        for name in ASSERTIONS:
            self.assertRegex(self.sources[name], r'type:\s*"assertion"')

    def test_shadow_outputs_use_audit_dataset(self):
        for name in WP04_ACTIONS - {"trading_price_features"}:
            with self.subTest(name=name):
                self.assertIn(
                    "schema: dataform.projectConfig.vars.auditDataset",
                    self.sources[name],
                )
        legacy = self.sources["trading_price_features"]
        self.assertIn('schema: "acciones_dataset"', legacy)
        bridge = self.sources["trading_price_features_wp04_shadow"]
        self.assertIn("useCanonicalPrices", bridge)
        self.assertIn("dataform.projectConfig.vars.auditDataset", bridge)
        self.assertIn("dataform.projectConfig.vars.operationalDataset", bridge)

    def test_no_join_using_in_wp04_sql(self):
        pattern = re.compile(r"(?is)\bJOIN\b[\s\S]{0,300}?\bUSING\s*\(")
        offenders = [
            name for name, source in self.sources.items() if pattern.search(source)
        ]
        self.assertEqual([], offenders)

    def test_price_canonical_separates_execution_and_return_series(self):
        source = self.sources["market_price_canonical"]
        for marker in (
            "raw_open",
            "raw_high",
            "raw_low",
            "raw_close",
            "adjusted_close",
            "INTRADAY_COMPLETE",
            "DAILY_FALLBACK_INCOMPLETE_INTRADAY",
            "minimumIntradayCoverage",
            "source_revision_ids",
            "reconciliation_blocks_quality",
            "CRYPTO_4H_COMPLETE",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("SUM(d.volume", source)

    def test_corporate_actions_are_pit_and_fail_closed(self):
        source = self.sources["corporate_actions_pit"]
        for column in (
            "source_published_at",
            "available_at",
            "ingested_at",
            "revision",
            "backtest_eligible",
            "quality_status",
        ):
            self.assertIn(column, source)
        canonical = self.sources["market_price_canonical"]
        self.assertIn("WHERE backtest_eligible", canonical)
        self.assertIn('quality_status = "ELIGIBLE_VERIFIED_PIT"', canonical)

    def test_features_use_adjusted_returns_and_raw_execution_levels(self):
        source = self.sources["trading_price_features_canonical_shadow"]
        self.assertIn("raw_open AS day_open", source)
        self.assertIn("raw_close AS day_close", source)
        self.assertIn("SAFE_DIVIDE(adjusted_close", source)
        self.assertIn('canonical_interval = "4h"', source)
        self.assertIn("adjusted_lag_6", source)
        self.assertIn("crypto_1200", source)
        self.assertIn("price_available_at", source)

    def test_feature_flag_defaults_to_legacy_rollback(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(workflow, r"useCanonicalPrices:\s*[\"']?false")
        bridge = self.sources["trading_price_features_wp04_shadow"]
        self.assertIn('=== "true"', bridge)
        self.assertIn("LEGACY_ROLLBACK", bridge)
        self.assertIn("CANONICAL_WP04", bridge)
        self.assertIn("trading_price_features_canonical_shadow", bridge)
        legacy = self.sources["trading_price_features"]
        self.assertNotIn("useCanonicalPrices", legacy)

    def test_reconciliation_and_fx_fail_closed(self):
        reconciliation = self.sources["price_source_reconciliation"]
        for status in (
            "MATCH",
            "WITHIN_TOLERANCE",
            "MATERIAL_MISMATCH",
            "SOURCE_MISSING",
            "STALE_SOURCE",
        ):
            self.assertIn(status, reconciliation)
        self.assertIn("requireSecondaryPriceSource", reconciliation)
        fx = self.sources["fx_rates_pit"]
        self.assertIn('"USD" AS base_currency', fx)
        self.assertIn('"CLP" AS quote_currency', fx)
        self.assertIn("usdClpTicker", fx)

    def test_dual_run_and_audit_never_promote(self):
        dual = self.sources["wp04_legacy_vs_canonical_shadow"]
        self.assertIn("FALSE AS promotion_eligible", dual)
        self.assertIn("FALSE AS production_change_allowed", dual)
        bridge = self.sources["trading_price_features_wp04_shadow"]
        self.assertIn("FALSE AS promotion_eligible", bridge)
        audit = self.sources["audit_canonical_prices"]
        self.assertIn("PRODUCTION_CHANGE_ALLOWED", audit)
        self.assertIn("LEGACY_COMPARISON_PROMOTION_ELIGIBLE", audit)
        self.assertIn("FEATURE_CONSUMED_BLOCKED_PRICE", audit)

    def test_raw_operations_are_additive_create_only(self):
        for name in OPERATIONS:
            source = self.sources[name].upper()
            self.assertIn("CREATE TABLE IF NOT EXISTS", source)
            self.assertNotIn("CREATE OR REPLACE TABLE", source)
            self.assertNotIn("DROP TABLE", source)
            self.assertNotIn("DELETE FROM", source)
            self.assertNotIn("UPDATE ", source)


if __name__ == "__main__":
    unittest.main()
