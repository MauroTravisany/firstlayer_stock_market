import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.capture_baseline import (
    LEGACY_CLASSIFICATION,
    CONFIGURATION_TABLES,
    RESULT_FAMILIES,
    BaselineValidationError,
    BaselineReadinessError,
    BigQueryReader,
    CloudInventoryReader,
    ReadOnlyViolation,
    assert_read_only_command,
    build_manifest,
    capture_configuration,
    main,
    sanitize,
    render_sqlx_query,
    validate_manifest,
    validate_manifest_readiness,
    validate_manifest_structure,
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
            "capture_started_at_utc": "2026-08-08T12:00:00.000000Z",
            "capture_completed_at_utc": "2026-08-08T12:00:05.000000Z",
            "bigquery_snapshot_as_of_utc": "2026-08-08T12:00:00.000000Z",
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

    def test_capture_metadata_does_not_change_state_checksum(self):
        first = build_manifest(**self.inputs)
        later_inputs = copy.deepcopy(self.inputs)
        later_inputs["capture_started_at_utc"] = "2026-08-08T13:00:00.000000Z"
        later_inputs["capture_completed_at_utc"] = "2026-08-08T13:00:08.000000Z"
        later_inputs["bigquery_snapshot_as_of_utc"] = "2026-08-08T13:00:00.000000Z"

        second = build_manifest(**later_inputs)

        self.assertEqual(first["manifest_checksum"], second["manifest_checksum"])

    def test_configuration_rows_with_duplicate_ids_are_canonicalized(self):
        class Reader:
            def __init__(self, reverse):
                self.reverse = reverse

            def rows(self, sql):
                if "trading_backtest_context_variants" not in sql:
                    return []
                rows = [
                    {"variant_id": "duplicate", "weight": 2},
                    {"variant_id": "duplicate", "weight": 1},
                ]
                return list(reversed(rows)) if self.reverse else rows

        first = capture_configuration(
            Reader(reverse=False), "stocks-437902", "acciones_dataset"
        )
        second = capture_configuration(
            Reader(reverse=True), "stocks-437902", "acciones_dataset"
        )

        self.assertEqual(first, second)
        self.assertEqual(
            first["backtest_context_variants"]["rows"],
            [
                {"variant_id": "duplicate", "weight": 1},
                {"variant_id": "duplicate", "weight": 2},
            ],
        )

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

    def test_git_tag_creation_and_deletion_are_rejected(self):
        for command in (
            ["git", "tag", "new-baseline-tag"],
            ["git", "tag", "--delete", "legacy-pre-audit-grade-2026-08"],
            ["git", "tag", "-d", "legacy-pre-audit-grade-2026-08"],
        ):
            with self.assertRaises(ReadOnlyViolation):
                assert_read_only_command(command)

    def test_structure_allows_a_registered_operational_blocker(self):
        blocked = copy.deepcopy(self.inputs)
        blocked["cloud"]["schedulers"][0]["state"] = "ENABLED"
        manifest = build_manifest(**blocked)

        validate_manifest_structure(manifest)

        with self.assertRaises(BaselineReadinessError):
            validate_manifest_readiness(manifest)

    def test_readiness_accepts_manifest_without_operational_blockers(self):
        manifest = build_manifest(**self.inputs)

        validate_manifest_structure(manifest)
        validate_manifest_readiness(manifest)

    def test_verify_cli_reports_structure_valid_with_blocker(self):
        blocked = copy.deepcopy(self.inputs)
        blocked["cloud"]["schedulers"][0]["state"] = "ENABLED"
        manifest = build_manifest(**blocked)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            output = io.StringIO()
            with mock.patch(
                "tools.capture_baseline.capture_live_baseline", return_value=manifest
            ), contextlib.redirect_stdout(output):
                exit_code = main(["--verify", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("BASELINE_STRUCTURE_VALID", output.getvalue())

    def test_verify_cli_strict_reports_not_ready_with_blocker(self):
        blocked = copy.deepcopy(self.inputs)
        blocked["cloud"]["schedulers"][0]["state"] = "ENABLED"
        manifest = build_manifest(**blocked)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            error = io.StringIO()
            output = io.StringIO()
            with mock.patch(
                "tools.capture_baseline.capture_live_baseline", return_value=manifest
            ), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                exit_code = main(["--verify", str(path), "--strict"])

        self.assertEqual(exit_code, 3)
        self.assertIn("BASELINE_NOT_READY", error.getvalue())

    def test_verify_cli_strict_reports_ready_without_blockers(self):
        manifest = build_manifest(**self.inputs)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            output = io.StringIO()
            with mock.patch(
                "tools.capture_baseline.capture_live_baseline", return_value=manifest
            ), contextlib.redirect_stdout(output):
                exit_code = main(["--verify", str(path), "--strict"])

        self.assertEqual(exit_code, 0)
        self.assertIn("BASELINE_READY", output.getvalue())

    def test_view_uses_explicit_live_fallback(self):
        class Metadata:
            table_type = "VIEW"

        class QueryJob:
            def result(self):
                return []

        class Client:
            def __init__(self):
                self.queries = []

            def get_table(self, table_reference):
                self.table_reference = table_reference
                return Metadata()

            def query(self, sql, **_kwargs):
                self.queries.append(sql)
                return QueryJob()

        client = Client()
        reader = BigQueryReader("stocks-437902", "us-east1", client=client)

        reader.rows_at_snapshot(
            "SELECT * FROM t FOR SYSTEM_TIME AS OF TIMESTAMP('2026-08-08T00:00:00Z')",
            "SELECT * FROM t",
            "source_view",
            "stocks-437902.acciones_dataset.source_view",
        )

        self.assertEqual(client.queries, ["SELECT * FROM t"])
        self.assertEqual(
            reader.snapshot_fallbacks,
            [
                {
                    "source_table": "source_view",
                    "source_type": "VIEW",
                    "fallback_reason": "TIME_TRAVEL_UNSUPPORTED_FOR_VIEW",
                    "exception_type": None,
                    "error_code": None,
                }
            ],
        )

    def test_base_table_uses_snapshot_query(self):
        class Metadata:
            table_type = "TABLE"

        class QueryJob:
            def result(self):
                return []

        class Client:
            def __init__(self):
                self.queries = []

            def get_table(self, _table_reference):
                return Metadata()

            def query(self, sql, **_kwargs):
                self.queries.append(sql)
                return QueryJob()

        client = Client()
        reader = BigQueryReader("stocks-437902", "us-east1", client=client)

        reader.rows_at_snapshot(
            "SELECT snapshot",
            "SELECT live",
            "source_table",
            "stocks-437902.acciones_dataset.source_table",
        )

        self.assertEqual(client.queries, ["SELECT snapshot"])
        self.assertEqual(reader.snapshot_fallbacks, [])

    def test_unsupported_source_type_fails(self):
        class Metadata:
            table_type = "EXTERNAL"

        class Client:
            def get_table(self, _table_reference):
                return Metadata()

        reader = BigQueryReader("stocks-437902", "us-east1", client=Client())

        with self.assertRaises(BaselineValidationError):
            reader.rows_at_snapshot("SELECT 1", "SELECT 1", "t", "p.d.t")

    def test_snapshot_metadata_permission_error_fails(self):
        class Client:
            def get_table(self, _table_reference):
                raise PermissionError("denied")

        reader = BigQueryReader("stocks-437902", "us-east1", client=Client())

        with self.assertRaises(PermissionError):
            reader.rows_at_snapshot("SELECT 1", "SELECT 1", "t", "p.d.t")

    def test_snapshot_metadata_authentication_error_fails(self):
        class AuthenticationError(Exception):
            pass

        class Client:
            def get_table(self, _table_reference):
                raise AuthenticationError("invalid credentials")

        reader = BigQueryReader("stocks-437902", "us-east1", client=Client())

        with self.assertRaises(AuthenticationError):
            reader.rows_at_snapshot("SELECT 1", "SELECT 1", "t", "p.d.t")

    def test_snapshot_metadata_network_error_fails(self):
        class Client:
            def get_table(self, _table_reference):
                raise ConnectionError("network unavailable")

        reader = BigQueryReader("stocks-437902", "us-east1", client=Client())

        with self.assertRaises(ConnectionError):
            reader.rows_at_snapshot("SELECT 1", "SELECT 1", "t", "p.d.t")

    def test_snapshot_sql_error_fails(self):
        class Metadata:
            table_type = "TABLE"

        class SqlError(Exception):
            pass

        class Client:
            def get_table(self, _table_reference):
                return Metadata()

            def query(self, _sql, **_kwargs):
                raise SqlError("invalid query")

        reader = BigQueryReader("stocks-437902", "us-east1", client=Client())

        with self.assertRaises(SqlError):
            reader.rows_at_snapshot("SELECT bad", "SELECT 1", "t", "p.d.t")

    def test_snapshot_timeout_fails(self):
        class Metadata:
            table_type = "TABLE"

        class Client:
            def get_table(self, _table_reference):
                return Metadata()

            def query(self, _sql, **_kwargs):
                raise TimeoutError("timed out")

        reader = BigQueryReader("stocks-437902", "us-east1", client=Client())

        with self.assertRaises(TimeoutError):
            reader.rows_at_snapshot("SELECT 1", "SELECT 1", "t", "p.d.t")

    def test_snapshot_unexpected_error_fails(self):
        class Metadata:
            table_type = "TABLE"

        class Client:
            def get_table(self, _table_reference):
                return Metadata()

            def query(self, _sql, **_kwargs):
                raise RuntimeError("unexpected")

        reader = BigQueryReader("stocks-437902", "us-east1", client=Client())

        with self.assertRaises(RuntimeError):
            reader.rows_at_snapshot("SELECT 1", "SELECT 1", "t", "p.d.t")

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
