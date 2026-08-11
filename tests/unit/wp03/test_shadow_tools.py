import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from tools import wp03_shadow_backfill as backfill
from tools import wp03_shadow_evidence as evidence


ROOT = Path(__file__).resolve().parents[3]


class ShadowBackfillToolTests(unittest.TestCase):
    def test_ticker_and_range_limits_fail_closed(self):
        self.assertEqual(["AAPL", "MSFT"], backfill.parse_tickers("aapl, msft"))
        with self.assertRaisesRegex(ValueError, "duplicates"):
            backfill.parse_tickers("AAPL,AAPL")
        with self.assertRaisesRegex(ValueError, "At most"):
            backfill.parse_tickers(
                ",".join(f"T{index}" for index in range(backfill.MAX_TICKERS_PER_RUN + 1))
            )
        with self.assertRaisesRegex(ValueError, "cannot be after"):
            backfill._validate_year_range(2026, 2025)
        with self.assertRaisesRegex(ValueError, "span at most"):
            backfill._validate_year_range(2010, 2026)
        with self.assertRaisesRegex(ValueError, "between 1"):
            backfill._validate_max_rows(0)
        with self.assertRaisesRegex(ValueError, "between 1"):
            backfill._validate_max_rows(backfill.MAX_ROWS_HARD_LIMIT + 1)

    def test_execute_scope_requires_isolated_shadow_dataset(self):
        self.assertEqual(
            "wp03_shadow",
            backfill._validated_shadow_dataset_id("wp03_shadow"),
        )
        with self.assertRaisesRegex(ValueError, "contains 'shadow'"):
            backfill._validated_shadow_dataset_id("acciones_dataset")

    def test_plan_checksum_ignores_capture_time_but_covers_scope(self):
        base = {
            "schema_version": 1,
            "operation": "WP03_SHADOW_SEC_BACKFILL",
            "git_sha": "a" * 40,
            "mapping_version": "mapping-v1",
            "mapping_sha256": "b" * 64,
            "start_year": 2024,
            "end_year": 2026,
            "tickers": ["AAPL"],
            "ticker_results": [{"ticker": "AAPL", "rows": 2}],
            "row_count": 2,
            "eligible_row_count": 2,
            "eligibility_reasons": {"VERIFIED": 2},
            "revision_set_sha256": "c" * 64,
            "max_rows": 100,
            "production_change_allowed": False,
            "generated_at": "2026-08-11T00:00:00Z",
        }
        first = backfill.finalize_plan(base)
        second = backfill.finalize_plan(
            {**base, "generated_at": "2026-08-12T00:00:00Z"}
        )
        self.assertEqual(first["plan_checksum"], second["plan_checksum"])
        changed = backfill.finalize_plan({**base, "tickers": ["MSFT"]})
        self.assertNotEqual(first["plan_checksum"], changed["plan_checksum"])
        self.assertEqual(
            first["plan_checksum"],
            backfill.verify_plan_checksum(first, first["plan_checksum"]),
        )
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            backfill.verify_plan_checksum(first, "0" * 64)

    def test_clean_checkout_requires_exact_sha_and_no_changes(self):
        with mock.patch.object(backfill, "_git_sha", return_value="a" * 40), mock.patch.object(
            backfill, "_run_git", return_value=""
        ):
            self.assertEqual(
                "a" * 40, backfill.verify_clean_checkout("a" * 40)
            )
        with mock.patch.object(backfill, "_git_sha", return_value="b" * 40):
            with self.assertRaisesRegex(RuntimeError, "Git SHA mismatch"):
                backfill.verify_clean_checkout("a" * 40)
        with mock.patch.object(backfill, "_git_sha", return_value="a" * 40), mock.patch.object(
            backfill, "_run_git", return_value=" M file.py"
        ):
            with self.assertRaisesRegex(RuntimeError, "clean checkout"):
                backfill.verify_clean_checkout("a" * 40)

    def test_plan_is_content_addressed_and_handles_not_applicable_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            mapping_path = Path(directory) / "mapping.json"
            mapping_path.write_text("{}", encoding="utf-8")
            mapping_module = types.SimpleNamespace(
                ticker_cik_map=lambda _config: (
                    "mapping-v1",
                    {
                        "AAPL": {
                            "financial_reporting": "SEC_EDGAR",
                            "cik": "0000320193",
                            "reporting_currency": "USD",
                        },
                        "BTC-USD": {"financial_reporting": "NOT_APPLICABLE"},
                    },
                    mapping_path,
                )
            )
            sec_source = types.SimpleNamespace(
                fetch_submissions=lambda _cik: {},
                fetch_companyfacts=lambda _cik: {},
                build_sec_statement_revisions=lambda *_args, **_kwargs: [
                    {
                        "revision_id": "revision-a",
                        "period_end_date": "2025-03-31",
                        "backtest_eligible": True,
                        "eligibility_reason": "VERIFIED",
                    },
                    {
                        "revision_id": "revision-b",
                        "period_end_date": "2021-03-31",
                        "backtest_eligible": True,
                        "eligibility_reason": "VERIFIED",
                    },
                ],
            )
            with mock.patch.object(
                backfill,
                "_load_runtime_modules",
                return_value={
                    "financial_mapping": mapping_module,
                    "sec_source": sec_source,
                },
            ), mock.patch.object(backfill, "_git_sha", return_value="a" * 40):
                plan, rows = backfill.build_backfill_plan(
                    tickers=["AAPL", "BTC-USD"],
                    start_year=2024,
                    end_year=2026,
                    expected_mapping_version="mapping-v1",
                    max_rows=10,
                    mapping_path=mapping_path,
                )
        self.assertEqual(1, len(rows))
        self.assertEqual("revision-a", rows[0]["revision_id"])
        self.assertEqual(1, plan["row_count"])
        self.assertEqual(1, plan["eligible_row_count"])
        self.assertRegex(plan["plan_checksum"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            "NOT_APPLICABLE", plan["ticker_results"][1]["status"]
        )

    def test_tool_has_no_operational_deploy_surface(self):
        source = (ROOT / "tools" / "wp03_shadow_backfill.py").read_text(
            encoding="utf-8"
        ).lower()
        for forbidden in (
            "gcloud run deploy",
            "scheduler jobs",
            "terraform apply",
            "paper_api",
            "submit_order",
        ):
            self.assertNotIn(forbidden, source)


class ShadowEvidenceToolTests(unittest.TestCase):
    def valid_results(self):
        return {
            "raw_summary": {
                "row_count": 10,
                "target_mapping_row_count": 10,
                "other_mapping_row_count": 0,
                "duplicate_revision_count": 0,
            },
            "canonical_summary": {
                "row_count": 8,
                "duplicate_revision_count": 0,
                "unexpected_mapping_count": 0,
                "invalid_revision_number_count": 0,
                "missing_availability_count": 0,
                "availability_mismatch_count": 0,
                "invalid_quality_count": 0,
            },
            "quarter_summary": {
                "row_count": 100,
                "incomplete_q4_count": 0,
                "available_after_signal_count": 0,
                "q4_component_after_annual_count": 0,
                "q4_component_after_signal_count": 0,
                "missing_currency_count": 0,
            },
            "ttm_summary": {
                "row_count": 50,
                "complete_row_count": 30,
                "invalid_complete_row_count": 0,
                "available_after_signal_count": 0,
                "missing_lineage_count": 0,
            },
            "earnings_summary": {
                "row_count": 20,
                "invalid_kind_count": 0,
                "availability_mismatch_count": 0,
                "invalid_revision_count": 0,
                "ineligible_row_count": 0,
                "duplicate_event_count": 0,
            },
            "earnings_context_summary": {
                "row_count": 100,
                "expected_after_signal_count": 0,
                "reported_after_signal_count": 0,
                "stale_recent_status_count": 0,
            },
            "valuation_summary": {
                "row_count": 100,
                "promotion_mode_violation_count": 0,
                "production_change_violation_count": 0,
                "price_after_signal_count": 0,
                "financial_after_signal_count": 0,
                "negative_multiple_count": 0,
                "cross_currency_arithmetic_count": 0,
            },
            "no_lookahead_summary": {"violation_count": 0},
            "comparison_summary": {
                "row_count": 100,
                "promotion_violation_count": 0,
            },
            "invalidation_summary": {
                "row_count": 4,
                "promotion_violation_count": 0,
                "classification_violation_count": 0,
                "recomputation_violation_count": 0,
            },
        }

    def test_queries_are_fixed_read_only_and_shadow_scoped(self):
        queries = evidence.build_queries(
            "stocks-437902", "wp03_shadow", "mapping-v1"
        )
        self.assertEqual(10, len(queries))
        for sql in queries.values():
            self.assertTrue(sql.lstrip().upper().startswith(("SELECT", "WITH")))
            self.assertIsNone(evidence.MUTATING_SQL.search(sql))
            self.assertIn("`stocks-437902.wp03_shadow.", sql)
        with self.assertRaisesRegex(evidence.EvidenceError, "contains 'shadow'"):
            evidence.build_queries(
                "stocks-437902", "acciones_dataset", "mapping-v1"
            )
        with self.assertRaisesRegex(evidence.EvidenceError, "mutating SQL"):
            evidence.assert_read_only_sql("MERGE target USING source ON TRUE")

    def test_valid_evidence_passes(self):
        result = evidence.evaluate_results(
            query_results=self.valid_results(), raw_schema_drift=[]
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual([], result["problems"])

    def test_prior_mapping_rows_are_warning_not_failure(self):
        fixture = self.valid_results()
        fixture["raw_summary"]["other_mapping_row_count"] = 5
        result = evidence.evaluate_results(
            query_results=fixture, raw_schema_drift=[]
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(
            "RAW_RETAINS_OTHER_MAPPING_VERSIONS",
            result["warnings"][0]["code"],
        )

    def test_lookahead_or_schema_drift_fails_closed(self):
        fixture = self.valid_results()
        fixture["no_lookahead_summary"]["violation_count"] = 1
        result = evidence.evaluate_results(
            query_results=fixture,
            raw_schema_drift=["MISSING_COLUMN:available_at"],
        )
        self.assertEqual("FAIL", result["status"])
        codes = {problem["code"] for problem in result["problems"]}
        self.assertIn("RAW_SCHEMA_DRIFT", codes)
        self.assertIn("NO_LOOKAHEAD_VIOLATION", codes)

    def test_empty_materialization_fails_closed(self):
        fixture = self.valid_results()
        fixture["comparison_summary"]["row_count"] = 0
        fixture["valuation_summary"]["row_count"] = 0
        result = evidence.evaluate_results(
            query_results=fixture, raw_schema_drift=[]
        )
        self.assertEqual("FAIL", result["status"])
        codes = {problem["code"] for problem in result["problems"]}
        self.assertIn("LEGACY_PIT_COMPARISON_EMPTY", codes)
        self.assertIn("VALUATION_SHADOW_EMPTY", codes)

    def test_evidence_tool_has_no_mutation_surface(self):
        source = (ROOT / "tools" / "wp03_shadow_evidence.py").read_text(
            encoding="utf-8"
        ).lower()
        for forbidden in (
            "create_table(",
            "delete_table(",
            "insert_rows",
            "load_table",
            "gcloud ",
            "terraform apply",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
