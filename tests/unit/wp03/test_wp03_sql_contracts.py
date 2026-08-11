from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "dataform" / "definitions"
FINANCIAL_FUNCTION = ROOT / "cloud-functions" / "financial_data"


class Wp03SqlContractTests(unittest.TestCase):
    def read(self, name):
        return (DEFINITIONS / name).read_text(encoding="utf-8")

    def test_financial_context_uses_canonical_quarters(self):
        sql = self.read("trading_financial_context_pit.sqlx")
        self.assertIn('${ref("financial_quarters_pit")}', sql)
        self.assertNotIn("COALESCE(s.report_date, s.period_end_date)", sql)
        self.assertNotIn("s.period_end_date <=", sql)
        self.assertIn("prior.currency = current.currency", sql)
        self.assertIn(
            "prior.quarter_structure_complete AS prior_year_quarter_structure_complete",
            sql,
        )
        self.assertGreaterEqual(
            sql.count("COALESCE(prior_year_quarter_structure_complete, FALSE)"),
            2,
        )

    def test_canonical_quarters_use_contemporaneous_q4_components(self):
        sql = self.read("financial_quarters_pit.sqlx")
        self.assertIn("c.available_at <= a.available_at", sql)
        self.assertIn("c.mapping_version = a.mapping_version", sql)
        self.assertIn(
            "DERIVED_Q4_ADDITIVE_FACTS_ONLY_FROM_CONTEMPORANEOUS_Q1_Q2_Q3",
            sql,
        )
        self.assertIn("derivation_component_revision_ids", sql)
        self.assertIn("component_currency_count", sql)
        self.assertIn("CAST(NULL AS FLOAT64) AS eps_basic", sql)
        self.assertIn("CAST(NULL AS FLOAT64) AS eps_diluted", sql)

    def test_earnings_context_uses_observation_availability(self):
        sql = self.read("trading_earnings_context_pit.sqlx")
        self.assertIn('e.event_kind = "EXPECTED"', sql)
        self.assertIn('e.event_kind = "REPORTED"', sql)
        self.assertGreaterEqual(
            sql.count("e.available_at <= p.signal_timestamp_utc"), 2
        )
        self.assertIn("reported_age_days BETWEEN 0 AND 5", sql)
        self.assertIn("expected_event_id", sql)
        self.assertIn("reported_event_id", sql)

    def test_ttm_requires_four_consecutive_single_currency_quarters(self):
        sql = self.read("financial_ttm_pit.sqlx")
        self.assertIn('${ref("financial_quarters_pit")}', sql)
        self.assertIn("distinct_quarter_count = 4", sql)
        self.assertIn("quarter_ordinal_span = 3", sql)
        self.assertIn("currency_count = 1", sql)
        self.assertIn("revenue_quarter_count = 4", sql)
        self.assertIn("net_income_quarter_count = 4", sql)
        self.assertIn("ttm_derivation_lineage_json", sql)

    def test_pit_valuation_uses_prior_price_and_positive_denominators(self):
        sql = self.read("portfolio_valuation_pit_shadow.sqlx")
        self.assertNotIn("financial_ratios_snapshot", sql)
        self.assertNotIn("forward_pe", sql.lower())
        self.assertIn("p.previous_close AS valuation_price", sql)
        self.assertIn("t.net_income_ttm > 0", sql)
        self.assertIn("t.revenue_ttm > 0", sql)
        self.assertIn("t.shareholders_equity_latest > 0", sql)
        self.assertIn('reporting_currency != "USD"', sql)
        self.assertIn("PIT_REPORTING_CURRENCY_UNKNOWN", sql)
        self.assertIn("PIT_DATA_INCOMPLETE", sql)
        self.assertIn("valuation_price_available_at <= signal_timestamp_utc", sql)
        self.assertIn('"SHADOW_ONLY" AS promotion_mode', sql)
        self.assertIn("FALSE AS production_change_allowed", sql)

    def test_canonical_financial_view_derives_mutable_lineage(self):
        canonical = self.read("financial_statements_pit.sqlx")
        raw = self.read("financial_statements_pit_raw.sqlx")
        self.assertIn('dependencies: ["financial_statements_pit_raw"]', canonical)
        self.assertIn('${ref("financial_statements_pit_raw")}', canonical)
        self.assertNotIn(".financial_statements_pit_raw`", canonical)
        self.assertIn("ROW_NUMBER() OVER", canonical)
        self.assertIn("source_is_amendment OR revision_number > 1", canonical)
        self.assertNotIn("revision_number INT64", raw)
        self.assertNotIn("is_restated BOOL", raw)
        self.assertIn("source_is_amendment BOOL NOT NULL", raw)

    def test_append_is_atomic_insert_only_merge(self):
        source = (
            FINANCIAL_FUNCTION / "custom_function" / "pit_bq_operations.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MERGE `{destination_table}`", source)
        self.assertIn("WHEN NOT MATCHED THEN", source)
        self.assertNotIn("WHEN MATCHED THEN", source)
        self.assertIn("PARTITION BY revision_id", source)
        self.assertNotIn('"revision_number",', source)
        self.assertIn('"source_is_amendment",', source)

    def test_legacy_results_are_explicitly_non_promotable(self):
        sql = self.read("wp03_legacy_invalidation.sqlx")
        self.assertIn("WP03_PIT_INVALIDATED", sql)
        self.assertIn("FALSE AS promotion_eligible", sql)
        self.assertIn("REQUIRES_RECOMPUTE_ON_WP03_PIT_SNAPSHOT", sql)
        self.assertIn('"trading_brain_runs"', sql)

    def test_dual_run_preserves_null_vs_zero_divergence(self):
        sql = self.read("wp03_legacy_vs_pit_shadow.sqlx")
        self.assertIn("FUNDAMENTAL_AVAILABILITY_CHANGED", sql)
        self.assertNotIn("COALESCE(l.legacy_revenue_yoy, 0)", sql)
        self.assertNotIn("COALESCE(p.pit_revenue_yoy, 0)", sql)

    def test_no_lookahead_assertion_covers_all_pit_consumers(self):
        sql = self.read("audit_no_lookahead.sqlx")
        self.assertIn('${ref("trading_earnings_context_pit")}', sql)
        self.assertNotIn('${ref("trading_earnings_context")}', sql)
        for marker in (
            "FINANCIAL_AVAILABLE_AFTER_SIGNAL",
            "PRIOR_YEAR_FINANCIAL_AVAILABLE_AFTER_SIGNAL",
            "Q4_COMPONENT_AVAILABLE_AFTER_ANNUAL_FILING",
            "Q4_COMPONENT_AVAILABLE_AFTER_SIGNAL",
            "EXPECTED_EARNINGS_AVAILABLE_AFTER_SIGNAL",
            "REPORTED_EARNINGS_AVAILABLE_AFTER_SIGNAL",
            "VALUATION_FINANCIAL_AVAILABLE_AFTER_SIGNAL",
            "VALUATION_PRICE_AVAILABLE_AFTER_SIGNAL",
        ):
            self.assertIn(marker, sql)

    def test_historical_shadow_uses_pit_earnings_not_legacy_status(self):
        sql = self.read("trading_historical_context_pit.sqlx")
        self.assertIn('${ref("trading_earnings_context_pit")}', sql)
        self.assertNotIn('SELECT * FROM ${ref("trading_earnings_context")}', sql)
        self.assertIn("PIT_YOY_UNAVAILABLE", sql)
        self.assertIn("PIT_TECHNICAL_CONTEXT_PENDING_WP04", sql)
        self.assertIn("WP03_FINANCIAL_AND_EARNINGS_PIT_ONLY", sql)

    def test_wp03_tests_are_discoverable(self):
        self.assertTrue((Path(__file__).parent / "__init__.py").is_file())


if __name__ == "__main__":
    unittest.main()
