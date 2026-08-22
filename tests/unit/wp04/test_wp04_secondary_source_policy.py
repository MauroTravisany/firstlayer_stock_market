import datetime as dt
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import wp04_secondary_source as secondary
from tools import wp04_shadow_evidence as evidence

ROOT = Path(__file__).resolve().parents[3]
UTC = dt.timezone.utc

class FakeResponse:
    def __init__(self, *, text, status_code=200, content_type="text/csv"):
        self.text = text; self.status_code = status_code; self.headers = {"Content-Type": content_type}

class Wp04SecondarySourcePolicyTests(unittest.TestCase):
    def valid_results(self):
        return {
            "raw_summary":{"row_count":700,"duplicate_revision_count":0,"available_before_bar_end_count":0,"invalid_ohlc_count":0,"yahoo_row_count":600,"stooq_row_count":0,"daily_row_count":300,"intraday_row_count":200,"hourly_row_count":200,"equity_row_count":500,"crypto_row_count":200,"fx_row_count":0,"diagnostic_fx_ohlc_row_count":0},
            "action_summary":{"row_count":10,"duplicate_action_count":0,"eligible_action_count":0,"invalid_eligible_availability_count":0},
            "calendar_summary":{"row_count":100,"duplicate_session_id_count":0,"duplicate_session_key_count":0,"invalid_duration_count":0,"xnys_count":20,"crypto_calendar_count":40,"fx_calendar_count":20},
            "reconciliation_summary":{"row_count":100,"duplicate_reconciliation_count":0,"material_mismatch_count":0,"source_missing_count":100,"stale_source_count":0,"unblocked_material_problem_count":0,"production_change_violation_count":0},
            "canonical_summary":{"row_count":200,"eligible_quality_count":200,"duplicate_price_id_count":0,"duplicate_canonical_key_count":0,"available_before_bar_end_count":0,"invalid_ohlc_count":0,"mixed_selection_count":0,"invalid_crypto_bucket_count":0,"production_change_violation_count":0,"intraday_selected_count":20},
            "feature_summary":{"row_count":100,"duplicate_feature_key_count":0,"price_after_signal_count":0,"production_change_violation_count":0,"blocked_price_consumption_count":0},
            "official_fx_raw_summary":{"row_count":20,"duplicate_revision_count":0,"invalid_rate_count":0,"invalid_source_count":0,"availability_mismatch_count":0,"reference_date_invalid_count":0,"publication_not_prior_count":0,"available_after_ingestion_count":0,"policy_invalid_count":0,"production_change_violation_count":0},
            "fx_summary":{"row_count":20,"duplicate_rate_id_count":0,"duplicate_rate_key_count":0,"invalid_rate_count":0,"production_change_violation_count":0},
            "bridge_summary":{"row_count":100,"canonical_source_count":100,"legacy_source_count":0,"promotion_violation_count":0,"production_change_violation_count":0},
            "comparison_summary":{"row_count":5,"promotion_violation_count":0,"production_change_violation_count":0},
            "audit_summary":{"violation_count":0},
        }
    def test_javascript_challenge_is_classified_without_html(self):
        def fake_get(*_args, **_kwargs): return FakeResponse(text="<!doctype html><html><script>challenge-platform</script>Enable JavaScript</html>", content_type="text/html")
        with self.assertRaises(secondary.SecondarySourceUnavailable) as raised:
            secondary.fetch_stooq_daily("aapl.us", start_date=dt.date(2026,1,1), end_date=dt.date(2026,1,5), get=fake_get)
        self.assertEqual("JAVASCRIPT_CHALLENGE", raised.exception.reason_code)
        self.assertNotIn("<html", str(raised.exception).lower())
    def test_valid_csv_and_api_key_not_in_status(self):
        captured = {}
        def fake_get(*_args, **kwargs):
            captured.update(kwargs); return FakeResponse(text="Date,Open,High,Low,Close,Volume\n2026-01-02,100,102,99,101,12345\n")
        rows = secondary.fetch_stooq_daily("aapl.us", start_date=dt.date(2026,1,1), end_date=dt.date(2026,1,5), api_key="secret-value", get=fake_get)
        self.assertEqual(1, len(rows)); self.assertEqual("secret-value", captured["params"]["apikey"])
        status = secondary.status_document(ticker="AAPL", provider_symbol="aapl.us", status="AVAILABLE", reason_code=None, required=False, api_key_configured=True, row_count=1, observed_at=dt.datetime(2026,1,5,tzinfo=UTC))
        self.assertNotIn("secret", str(status).lower())
    def test_optional_outage_is_warning(self):
        with patch.dict(os.environ, {"WP04_REQUIRE_SECONDARY_SOURCE":"false"}):
            result = evidence.evaluate(results=self.valid_results(), schema_drift={table:[] for table in evidence.CONTRACT_TABLES})
        self.assertEqual("PASS", result["status"]); self.assertEqual(0, result["hard_gate_count"])
        self.assertIn("SECONDARY_SOURCE_UNAVAILABLE_OPTIONAL", {row["code"] for row in result["warnings"]})
    def test_required_outage_fails_closed(self):
        with patch.dict(os.environ, {"WP04_REQUIRE_SECONDARY_SOURCE":"true"}):
            result = evidence.evaluate(results=self.valid_results(), schema_drift={table:[] for table in evidence.CONTRACT_TABLES})
        self.assertEqual("FAIL", result["status"])
        self.assertIn("STOOQ_ROWS_MISSING", {row["code"] for row in result["problems"]})
    def test_windowed_entrypoint_exposes_all_provider_controls(self):
        source = (ROOT / "tools" / "wp04_shadow_backfill_windowed.py").read_text(encoding="utf-8")
        for marker in ("wp04_quarantine_planner", "--require-secondary-source", "--stooq-api-key-env", "--bcch-api-token-env"):
            self.assertIn(marker, source)
        self.assertNotIn("bypass", source.lower())

if __name__ == "__main__": unittest.main()
