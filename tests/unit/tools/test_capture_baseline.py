import copy
import tempfile
import unittest
from pathlib import Path

from tools.capture_baseline import (
    LEGACY_CLASSIFICATION,
    CONFIGURATION_TABLES,
    RESULT_FAMILIES,
    BaselineValidationError,
    BigQueryReader,
    CloudInventoryReader,
    ReadOnlyViolation,
    assert_read_only_command,
    build_manifest,
    sanitize,
    render_sqlx_query,
    validate_manifest,
)


class CaptureBaselineTest(unittest.TestCase):
    def setUp(self):
        results = []
        for result_family, source_table, *_rest in RESULT_FAMILIES:
            results.append(
                {
                    "result_family": result_family,
                    "source_table": source_table,
                    "row_count": 10,
                    "date_start": "2020-01-01",
                    "date_end": "2026-08-07",
                    "results_checksum": f"checksum-{result_family}",
                    "legacy_classification": LEGACY_CLASSIFICATION,
                    "promotion_eligible": False,
                }
            )
        self.inputs = {
            "baseline_ref": "legacy-pre-audit-grade-2026-08",
            "baseline_git_sha": "f7c27dbf6b4293e4ba2755a642d2f616d98b3844",
            "repository": {
                "configuration": {
                    family: {"rows": []} for family, _table, _order in CONFIGURATION_TABLES
                },
            },
            "cloud": {
                "schedulers": [{"name": "strategy-brain-generate", "state": "PAUSED"}],
                "services": [{"name": "papertradeexecutor", "execution_mode": "paper"}],
                "dataform_release": {"name": "release", "gitCommitish": "main"},
            },
            "results": results,
            "policy": {
                "rows": [
                    {
                        "ticker": "AAPL",
                        "execution_mode": "SHADOW_ONLY",
                        "champion_strategy_version": "v2",
                    }
                ],
                "strategy_brain_statuses": ["BACKTEST_ONLY"],
                "production_change_allowed_values": [False],
                "alpaca_execution_modes": ["paper"],
            },
        }

    def test_repeated_capture_has_same_checksum(self):
        self.inputs["repository"]["configuration"]["watchlist"] = {
            "rows": [{"ticker": "AAPL", "enabled": True}]
        }
        first = build_manifest(**self.inputs)
        second_inputs = copy.deepcopy(self.inputs)
        second_inputs["repository"]["configuration"]["watchlist"] = {
            "rows": [{"enabled": True, "ticker": "AAPL"}]
        }
        second = build_manifest(**second_inputs)

        self.assertEqual(first["manifest_checksum"], second["manifest_checksum"])

    def test_legacy_results_are_never_promotion_eligible(self):
        manifest = build_manifest(**self.inputs)

        validate_manifest(manifest)
        self.assertTrue(
            all(not row["promotion_eligible"] for row in manifest["legacy_results"])
        )

    def test_non_shadow_policy_is_rejected(self):
        unsafe = copy.deepcopy(self.inputs)
        unsafe["policy"]["rows"][0]["execution_mode"] = "PAPER_CHAMPION"
        manifest = build_manifest(**unsafe)

        with self.assertRaises(BaselineValidationError):
            validate_manifest(manifest)

    def test_strategy_brain_promotion_permission_is_rejected(self):
        unsafe = copy.deepcopy(self.inputs)
        unsafe["policy"]["production_change_allowed_values"] = [False, True]
        manifest = build_manifest(**unsafe)

        with self.assertRaises(BaselineValidationError):
            validate_manifest(manifest)

    def test_manifest_tampering_is_rejected(self):
        manifest = build_manifest(**self.inputs)
        manifest["legacy_results"][0]["row_count"] = 11

        with self.assertRaises(BaselineValidationError):
            validate_manifest(manifest)

    def test_sensitive_environment_values_are_redacted(self):
        value = [
            {"name": "PROJECT_ID", "value": "stocks-437902"},
            {"name": "OPENAI_API_KEY", "value": "must-not-leak"},
            {"name": "DISCORD_WEBHOOK_URL", "value": "must-not-leak"},
        ]

        redacted = sanitize(value)

        self.assertEqual(redacted[0]["value"], "stocks-437902")
        self.assertEqual(redacted[1]["value"], "<redacted>")
        self.assertEqual(redacted[2]["value"], "<redacted>")

    def test_manifest_with_unredacted_secret_is_rejected(self):
        unsafe = copy.deepcopy(self.inputs)
        unsafe["repository"]["configuration"]["api_token"] = "must-not-leak"
        manifest = build_manifest(**unsafe)

        with self.assertRaises(BaselineValidationError):
            validate_manifest(manifest)

    def test_only_read_only_cloud_and_bigquery_commands_are_allowed(self):
        allowed = [
            ["bq", "query", "--use_legacy_sql=false", "SELECT 1"],
            ["gcloud", "scheduler", "jobs", "list", "--format=json"],
            ["gcloud", "run", "services", "list", "--format=json"],
            ["gcloud", "dataform", "release-configs", "describe", "production"],
        ]
        forbidden = [
            ["bq", "query", "--use_legacy_sql=false", "DELETE FROM x WHERE TRUE"],
            ["gcloud", "scheduler", "jobs", "update", "http", "job"],
            ["gcloud", "run", "deploy", "service"],
            ["gcloud", "dataform", "release-configs", "update", "production"],
        ]

        for command in allowed:
            assert_read_only_command(command)
        for command in forbidden:
            with self.assertRaises(ReadOnlyViolation):
                assert_read_only_command(command)

    def test_bigquery_reader_rejects_mutation_before_client_call(self):
        class FailingClient:
            def query(self, *_args, **_kwargs):
                raise AssertionError("client must not be called")

        reader = BigQueryReader("stocks-437902", "us-east1", client=FailingClient())

        with self.assertRaises(ReadOnlyViolation):
            reader.rows("DELETE FROM `stocks-437902.acciones_dataset.x` WHERE TRUE")

    def test_cloud_inventory_uses_get_and_sanitizes_service_secrets(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Session:
            def __init__(self):
                self.urls = []

            def get(self, url, timeout):
                self.urls.append((url, timeout))
                if "cloudscheduler" in url:
                    return Response({"jobs": [{"name": "job", "state": "ENABLED"}]})
                if "run.googleapis" in url:
                    return Response(
                        {
                            "services": [
                                {
                                    "name": "projects/p/locations/l/services/papertradeexecutor",
                                    "template": {
                                        "containers": [
                                            {
                                                "env": [
                                                    {"name": "PAPER_EXECUTION_MODE", "value": "paper"},
                                                    {"name": "ALPACA_API_KEY", "value": "hidden"},
                                                ]
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    )
                return Response({"name": "release", "gitCommitish": "main"})

        session = Session()
        inventory = CloudInventoryReader(
            "stocks-437902", "us-east1", session=session
        ).capture("portfolio-valuation", "production")

        env = inventory["services"][0]["template"]["containers"][0]["env"]
        self.assertEqual(env[0]["value"], "paper")
        self.assertEqual(env[1]["value"], "<redacted>")
        self.assertEqual(len(session.urls), 3)

    def test_sqlx_renderer_removes_config_and_resolves_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.sqlx"
            path.write_text(
                'config { type: "table", assertions: { rowConditions: ["x"] } }\n'
                'SELECT * FROM ${ref("source_table")}',
                encoding="utf-8",
            )

            query = render_sqlx_query(path, "stocks-437902", "acciones_dataset")

        self.assertEqual(
            query,
            "SELECT * FROM `stocks-437902.acciones_dataset.source_table`",
        )


if __name__ == "__main__":
    unittest.main()
