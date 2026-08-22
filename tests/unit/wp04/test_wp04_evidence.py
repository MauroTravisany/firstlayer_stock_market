from pathlib import Path
import unittest

from tools import wp04_shadow_evidence as evidence


ROOT = Path(__file__).resolve().parents[3]


class Wp04EvidenceTests(unittest.TestCase):
    def valid_results(self):
        return {
            "raw_summary": {
                "row_count": 900,
                "duplicate_revision_count": 0,
                "available_before_bar_end_count": 0,
                "invalid_ohlc_count": 0,
                "yahoo_row_count": 700,
                "stooq_row_count": 200,
                "daily_row_count": 300,
                "intraday_row_count": 400,
                "hourly_row_count": 200,
                "equity_row_count": 700,
                "crypto_row_count": 200,
                "fx_row_count": 0,
                "diagnostic_fx_ohlc_row_count": 0,
            },
            "action_summary": {
                "row_count": 20,
                "duplicate_action_count": 0,
                "eligible_action_count": 0,
                "invalid_eligible_availability_count": 0,
                "fail_closed_action_count": 20,
            },
            "calendar_summary": {
                "row_count": 5000,
                "duplicate_session_id_count": 0,
                "duplicate_session_key_count": 0,
                "invalid_duration_count": 0,
                "xnys_count": 1000,
                "crypto_calendar_count": 2000,
                "fx_calendar_count": 1000,
            },
            "reconciliation_summary": {
                "row_count": 200,
                "duplicate_reconciliation_count": 0,
                "material_mismatch_count": 2,
                "source_missing_count": 0,
                "stale_source_count": 0,
                "unblocked_material_problem_count": 0,
                "production_change_violation_count": 0,
            },
            "canonical_summary": {
                "row_count": 500,
                "eligible_quality_count": 450,
                "duplicate_price_id_count": 0,
                "duplicate_canonical_key_count": 0,
                "available_before_bar_end_count": 0,
                "invalid_ohlc_count": 0,
                "mixed_selection_count": 0,
                "invalid_crypto_bucket_count": 0,
                "production_change_violation_count": 0,
                "intraday_selected_count": 50,
            },
            "feature_summary": {
                "row_count": 450,
                "duplicate_feature_key_count": 0,
                "price_after_signal_count": 0,
                "production_change_violation_count": 0,
                "blocked_price_consumption_count": 0,
            },
            "official_fx_raw_summary": {
                "row_count": 100,
                "duplicate_revision_count": 0,
                "invalid_rate_count": 0,
                "invalid_source_count": 0,
                "missing_first_observed_count": 0,
                "retroactive_availability_count": 0,
                "availability_mismatch_count": 0,
                "reference_date_invalid_count": 0,
                "publication_not_prior_count": 0,
                "available_after_ingestion_count": 0,
                "policy_invalid_count": 0,
                "snapshot_presented_as_vintage_count": 0,
                "eligible_without_publication_evidence_count": 0,
                "production_change_violation_count": 0,
            },
            "fx_summary": {
                "row_count": 100,
                "duplicate_rate_id_count": 0,
                "duplicate_rate_key_count": 0,
                "invalid_rate_count": 0,
                "revision_used_before_observation_count": 0,
                "production_change_violation_count": 0,
            },
            "bridge_summary": {
                "row_count": 450,
                "canonical_source_count": 450,
                "legacy_source_count": 0,
                "promotion_violation_count": 0,
                "production_change_violation_count": 0,
            },
            "comparison_summary": {
                "row_count": 5,
                "promotion_violation_count": 0,
                "production_change_violation_count": 0,
            },
            "audit_summary": {"violation_count": 0},
        }

    def evaluate(self, rows=None):
        return evidence.evaluate(
            results=rows or self.valid_results(),
            schema_drift={table: [] for table in evidence.CONTRACT_TABLES},
        )

    def test_valid_evidence_passes_without_yahoo_fx_rows(self):
        result = self.evaluate()
        self.assertEqual("PASS", result["status"])
        self.assertEqual(0, result["hard_gate_count"])
        policy = result["official_fx_source_policy"]
        self.assertEqual("BCCH_BDE", policy["provider"])
        self.assertEqual("F073.TCO.PRE.Z.D", policy["series_id"])

    def test_missing_official_fx_raw_fails_closed(self):
        rows = self.valid_results()
        rows["official_fx_raw_summary"]["row_count"] = 0
        result = self.evaluate(rows)
        self.assertIn(
            "OFFICIAL_FX_RAW_EMPTY",
            {row["code"] for row in result["problems"]},
        )

    def test_every_official_fx_gate_fails_closed(self):
        mappings = {
            "duplicate_revision_count": "OFFICIAL_FX_DUPLICATE_REVISION",
            "invalid_rate_count": "OFFICIAL_FX_INVALID_RATE",
            "availability_mismatch_count": "OFFICIAL_FX_AVAILABILITY_MISMATCH",
            "missing_first_observed_count": "OFFICIAL_FX_FIRST_OBSERVED_MISSING",
            "retroactive_availability_count": "OFFICIAL_FX_RETROACTIVE_AVAILABILITY",
            "reference_date_invalid_count": "OFFICIAL_FX_REFERENCE_DATE_INVALID",
            "publication_not_prior_count": "OFFICIAL_FX_PUBLICATION_NOT_PRIOR",
            "available_after_ingestion_count": "OFFICIAL_FX_AVAILABLE_AFTER_INGESTION",
            "policy_invalid_count": "OFFICIAL_FX_POLICY_INVALID",
            "snapshot_presented_as_vintage_count": "OFFICIAL_FX_SNAPSHOT_AS_VINTAGE",
            "eligible_without_publication_evidence_count": (
                "OFFICIAL_FX_ELIGIBLE_WITHOUT_PUBLICATION_EVIDENCE"
            ),
            "production_change_violation_count": "OFFICIAL_FX_PRODUCTION_CHANGE",
        }
        for field, expected in mappings.items():
            with self.subTest(field=field):
                rows = self.valid_results()
                rows["official_fx_raw_summary"][field] = 1
                result = self.evaluate(rows)
                self.assertIn(expected, {row["code"] for row in result["problems"]})

    def test_revision_used_before_observation_fails_closed(self):
        rows = self.valid_results()
        rows["fx_summary"]["revision_used_before_observation_count"] = 1
        result = self.evaluate(rows)
        self.assertIn(
            "OFFICIAL_FX_REVISION_USED_BEFORE_OBSERVATION",
            {row["code"] for row in result["problems"]},
        )

    def test_yahoo_fx_rows_are_diagnostic_only(self):
        rows = self.valid_results()
        rows["raw_summary"]["fx_row_count"] = 2
        rows["raw_summary"]["diagnostic_fx_ohlc_row_count"] = 2
        result = self.evaluate(rows)
        self.assertEqual("PASS", result["status"])
        warning = next(
            row
            for row in result["warnings"]
            if row["code"] == "DIAGNOSTIC_FX_OHLC_ROWS_PRESENT"
        )
        self.assertFalse(warning["eligible"])

    def test_mixed_granularity_and_audit_violation_fail_closed(self):
        rows = self.valid_results()
        rows["canonical_summary"]["mixed_selection_count"] = 1
        rows["audit_summary"]["violation_count"] = 1
        result = self.evaluate(rows)
        codes = {row["code"] for row in result["problems"]}
        self.assertIn("MIXED_DAILY_INTRADAY_SELECTION", codes)
        self.assertIn("AUDIT_CANONICAL_PRICE_VIOLATION", codes)

    def test_queries_are_read_only_shadow_scoped_and_include_official_raw(self):
        queries = evidence.build_queries("stocks-437902", "wp04_shadow_test")
        self.assertEqual(11, len(queries))
        self.assertIn("diagnostic_fx_ohlc_row_count", queries["raw_summary"])
        self.assertIn("fx_rate_raw", queries["official_fx_raw_summary"])
        self.assertIn("source_reference_date", queries["official_fx_raw_summary"])
        for sql in queries.values():
            self.assertTrue(sql.lstrip().upper().startswith(("SELECT", "WITH")))
            self.assertIsNone(evidence.MUTATING.search(sql))
            self.assertIn("`stocks-437902.wp04_shadow_test.", sql)

    def test_evidence_tool_has_no_mutation_surface(self):
        source = (ROOT / "tools" / "wp04_shadow_evidence.py").read_text(
            encoding="utf-8"
        ).lower()
        for forbidden in (
            "create_table(",
            "delete_table(",
            "load_table",
            "insert_rows",
            "terraform apply",
            "gcloud ",
            "submit_order",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
