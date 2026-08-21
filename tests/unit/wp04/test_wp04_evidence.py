from pathlib import Path
import unittest

from tools import wp04_shadow_evidence as evidence

ROOT = Path(__file__).resolve().parents[3]

class Wp04EvidenceTests(unittest.TestCase):
    def valid_results(self):
        return {
            "raw_summary":{"row_count":1000,"duplicate_revision_count":0,"available_before_bar_end_count":0,"invalid_ohlc_count":0,"yahoo_row_count":700,"stooq_row_count":200,"bcch_row_count":100,"invalid_bcch_reference_count":0,"daily_row_count":300,"intraday_row_count":400,"hourly_row_count":200,"equity_row_count":700,"crypto_row_count":200,"fx_row_count":100},
            "action_summary":{"row_count":20,"duplicate_action_count":0,"eligible_action_count":0,"invalid_eligible_availability_count":0,"fail_closed_action_count":20},
            "calendar_summary":{"row_count":5000,"duplicate_session_id_count":0,"duplicate_session_key_count":0,"invalid_duration_count":0,"xnys_count":1000,"crypto_calendar_count":2000,"fx_calendar_count":1000},
            "reconciliation_summary":{"row_count":200,"duplicate_reconciliation_count":0,"material_mismatch_count":2,"source_missing_count":0,"stale_source_count":0,"unblocked_material_problem_count":0,"production_change_violation_count":0},
            "canonical_summary":{"row_count":500,"eligible_quality_count":450,"duplicate_price_id_count":0,"duplicate_canonical_key_count":0,"available_before_bar_end_count":0,"invalid_ohlc_count":0,"mixed_selection_count":0,"invalid_crypto_bucket_count":0,"production_change_violation_count":0,"intraday_selected_count":50},
            "feature_summary":{"row_count":450,"duplicate_feature_key_count":0,"price_after_signal_count":0,"production_change_violation_count":0,"blocked_price_consumption_count":0},
            "fx_summary":{"row_count":100,"duplicate_rate_id_count":0,"duplicate_rate_key_count":0,"invalid_rate_count":0,"production_change_violation_count":0,"bcch_provider_count":100,"official_quality_count":100},
            "bridge_summary":{"row_count":450,"canonical_source_count":450,"legacy_source_count":0,"promotion_violation_count":0,"production_change_violation_count":0},
            "comparison_summary":{"row_count":5,"promotion_violation_count":0,"production_change_violation_count":0},
            "audit_summary":{"violation_count":0},
        }
    def test_valid_evidence_passes_with_declared_warnings(self):
        result = evidence.evaluate(results=self.valid_results(), schema_drift={table:[] for table in evidence.CONTRACT_TABLES})
        self.assertEqual("PASS", result["status"])
        self.assertEqual(0, result["hard_gate_count"])
        self.assertEqual("BCCH_BDE", result["fx_reference_policy"]["provider"])
    def test_missing_official_fx_fails_closed(self):
        rows = self.valid_results(); rows["raw_summary"]["bcch_row_count"] = 0; rows["fx_summary"]["bcch_provider_count"] = 0; rows["fx_summary"]["official_quality_count"] = 0
        result = evidence.evaluate(results=rows, schema_drift={table:[] for table in evidence.CONTRACT_TABLES})
        codes = {row["code"] for row in result["problems"]}
        self.assertIn("OFFICIAL_USD_CLP_SOURCE_MISSING", codes)
        self.assertIn("FX_RATE_NOT_SOURCED_FROM_BCCH", codes)
        self.assertIn("OFFICIAL_FX_QUALITY_MISSING", codes)
    def test_mixed_granularity_and_audit_violation_fail_closed(self):
        rows = self.valid_results(); rows["canonical_summary"]["mixed_selection_count"] = 1; rows["audit_summary"]["violation_count"] = 1
        result = evidence.evaluate(results=rows, schema_drift={table:[] for table in evidence.CONTRACT_TABLES})
        codes = {row["code"] for row in result["problems"]}
        self.assertIn("MIXED_DAILY_INTRADAY_SELECTION", codes)
        self.assertIn("AUDIT_CANONICAL_PRICE_VIOLATION", codes)
    def test_queries_are_read_only_shadow_scoped_and_include_bcch(self):
        queries = evidence.build_queries("stocks-437902", "wp04_shadow_test")
        self.assertEqual(10, len(queries))
        self.assertIn("bcch_row_count", queries["raw_summary"])
        self.assertIn("bcch_provider_count", queries["fx_summary"])
        for sql in queries.values():
            self.assertTrue(sql.lstrip().upper().startswith(("SELECT","WITH")))
            self.assertIsNone(evidence.MUTATING.search(sql))
            self.assertIn("`stocks-437902.wp04_shadow_test.", sql)
    def test_evidence_tool_has_no_mutation_surface(self):
        source = (ROOT / "tools" / "wp04_shadow_evidence.py").read_text(encoding="utf-8").lower()
        for forbidden in ("create_table(","delete_table(","load_table","insert_rows","terraform apply","gcloud ","submit_order"):
            self.assertNotIn(forbidden, source)

if __name__ == "__main__": unittest.main()
