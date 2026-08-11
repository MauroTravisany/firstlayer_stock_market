from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "dataform" / "definitions"


class Wp03SqlContractTests(unittest.TestCase):
    def read(self, name):
        return (DEFINITIONS / name).read_text(encoding="utf-8")

    def test_financial_context_uses_verified_availability_not_period_end_fallback(self):
        sql = self.read("trading_financial_context_pit.sqlx")
        self.assertIn("s.available_at <= p.signal_timestamp_utc", sql)
        self.assertNotIn("COALESCE(s.report_date, s.period_end_date)", sql)
        self.assertNotIn("s.period_end_date <=", sql)

    def test_earnings_context_uses_observation_availability(self):
        sql = self.read("trading_earnings_context.sqlx")
        self.assertIn('e.event_kind = "EXPECTED"', sql)
        self.assertIn('e.event_kind = "REPORTED"', sql)
        self.assertGreaterEqual(sql.count("e.available_at <= p.signal_timestamp_utc"), 2)

    def test_ttm_converts_annual_duration_to_q4(self):
        sql = self.read("financial_ttm_pit.sqlx")
        self.assertIn("DERIVED_Q4_FROM_FY_MINUS_Q1_Q2_Q3", sql)
        self.assertIn("revenue - q123_revenue", sql)
        self.assertIn("net_income - q123_net_income", sql)
        self.assertIn("quarter_count = 4 AND normalized_quarter_count = 4", sql)

    def test_pit_valuation_does_not_use_legacy_yahoo_ratio_snapshot(self):
        sql = self.read("portfolio_valuation_pit_shadow.sqlx")
        self.assertNotIn("financial_ratios_snapshot", sql)
        self.assertNotIn("forward_pe", sql.lower())
        self.assertIn("shares_outstanding_latest", sql)
        self.assertIn("revenue_ttm", sql)
        self.assertIn('"SHADOW_ONLY" AS promotion_mode', sql)
        self.assertIn("FALSE AS production_change_allowed", sql)

    def test_legacy_results_are_explicitly_non_promotable(self):
        sql = self.read("wp03_legacy_invalidation.sqlx")
        self.assertIn("WP03_PIT_INVALIDATED", sql)
        self.assertIn("FALSE AS promotion_eligible", sql)
        self.assertIn("REQUIRES_RECOMPUTE_ON_WP03_PIT_SNAPSHOT", sql)

    def test_no_lookahead_assertion_covers_all_pit_consumers(self):
        sql = self.read("audit_no_lookahead.sqlx")
        for marker in (
            "FINANCIAL_AVAILABLE_AFTER_SIGNAL",
            "PRIOR_YEAR_FINANCIAL_AVAILABLE_AFTER_SIGNAL",
            "EXPECTED_EARNINGS_AVAILABLE_AFTER_SIGNAL",
            "REPORTED_EARNINGS_AVAILABLE_AFTER_SIGNAL",
            "VALUATION_FINANCIAL_AVAILABLE_AFTER_SIGNAL",
        ):
            self.assertIn(marker, sql)


if __name__ == "__main__":
    unittest.main()
