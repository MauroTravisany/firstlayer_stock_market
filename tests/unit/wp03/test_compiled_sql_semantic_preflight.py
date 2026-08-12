import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "tools" / "wp03_compiled_sql_semantic_preflight.py"
spec = importlib.util.spec_from_file_location("wp03_semantic_preflight", TOOL_PATH)
preflight = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)

PROJECT = "stocks-437902"
OPERATIONAL = "acciones_dataset"
VALIDATION = "acciones_dataset_shadow_wp03_schema_check_20260812"
COMPILATION = (
    "projects/stocks-437902/locations/us-east1/repositories/"
    "stock-market/compilationResults/test"
)
SHA = "a" * 40


def target(name, schema=VALIDATION):
    return {"database": PROJECT, "schema": schema, "name": name}


def relation(name, dependencies=(), sql=None):
    return {
        "target": target(name),
        "canonicalTarget": target(name, "acciones_dataset"),
        "filePath": f"definitions/{name}.sqlx",
        "relation": {
            "dependencyTargets": list(dependencies),
            "disabled": False,
            "selectQuery": sql or f"SELECT '{name}' AS model_name",
            "relationType": "TABLE",
        },
    }


def operation(name):
    return {
        "target": target(name),
        "canonicalTarget": target(name, "acciones_dataset"),
        "filePath": f"definitions/{name}.sqlx",
        "operations": {
            "dependencyTargets": [],
            "disabled": False,
            "hasOutput": True,
            "queries": [
                f"CREATE TABLE IF NOT EXISTS `{PROJECT}.{VALIDATION}.{name}` "
                "(revision_id STRING)"
            ],
        },
    }


def assertion(name, parent):
    return {
        "target": target(f"assert_{name}"),
        "canonicalTarget": target(f"assert_{name}", "assertions"),
        "filePath": f"definitions/{name}.sqlx",
        "assertion": {
            "dependencyTargets": [target(parent)],
            "parentAction": target(parent),
            "disabled": False,
            "selectQuery": (
                f"SELECT * FROM `{PROJECT}.{VALIDATION}.{parent}` WHERE FALSE"
            ),
        },
    }


def operational(name):
    return target(name, OPERATIONAL)


def action_fixture(*, ambiguous_quarters=False):
    rows = [
        operation("financial_statements_pit_raw"),
        relation(
            "financial_statements_pit",
            [target("financial_statements_pit_raw")],
        ),
        relation(
            "financial_quarters_pit",
            [
                target("financial_statements_pit"),
                operational("trading_price_features"),
            ],
            "SELECT AMBIGUOUS AS ticker"
            if ambiguous_quarters
            else "SELECT 'ticker' AS ticker",
        ),
        relation(
            "financial_ttm_pit",
            [target("financial_quarters_pit")],
        ),
        relation(
            "earnings_events_pit",
            [operational("macro_earnings_calendar")],
        ),
        relation(
            "trading_financial_context_pit",
            [
                target("financial_ttm_pit"),
                operational("trading_price_features"),
            ],
        ),
        relation(
            "trading_earnings_context_pit",
            [
                target("earnings_events_pit"),
                operational("trading_price_features"),
            ],
        ),
        relation(
            "portfolio_valuation_pit_shadow",
            [
                target("financial_ttm_pit"),
                operational("trading_price_features"),
                operational("asset_profile"),
                operational("valuation_model_profile"),
            ],
        ),
        relation(
            "trading_historical_context_pit",
            [
                target("trading_financial_context_pit"),
                target("trading_earnings_context_pit"),
                operational("trading_historical_context"),
            ],
        ),
        relation(
            "wp03_legacy_vs_pit_shadow",
            [
                target("portfolio_valuation_pit_shadow"),
                target("trading_historical_context_pit"),
                operational("portfolio_valuation_daily"),
            ],
        ),
        relation("wp03_legacy_invalidation"),
        relation(
            "audit_no_lookahead",
            [
                target("financial_quarters_pit"),
                target("financial_ttm_pit"),
                target("earnings_events_pit"),
                target("trading_earnings_context_pit"),
                target("portfolio_valuation_pit_shadow"),
            ],
        ),
        assertion("financial_quarters_pit", "financial_quarters_pit"),
        assertion("audit_no_lookahead", "audit_no_lookahead"),
    ]
    return rows


def build(rows=None):
    rows = rows or action_fixture()
    return preflight.build_plan(
        rows,
        project_id=PROJECT,
        operational_dataset=OPERATIONAL,
        validation_dataset=VALIDATION,
        compilation_result=COMPILATION,
        git_sha=SHA,
        actions_document_sha256="b" * 64,
    )


class FakeSchemaField:
    def __init__(self, name, field_type, mode="NULLABLE"):
        self.name = name
        self.field_type = field_type
        self.mode = mode


class FakeTable:
    def __init__(self, table_id, schema=None):
        self.table_id = table_id
        self.schema = list(schema or [])
        self.labels = {}


class FakeQueryJobConfig:
    def __init__(self, dry_run=False, use_query_cache=True):
        self.dry_run = dry_run
        self.use_query_cache = use_query_cache


class FakeJob:
    def __init__(self, total_bytes_processed=123):
        self.total_bytes_processed = total_bytes_processed

    def result(self, timeout=None):
        return []


class FakeClient:
    def __init__(self, *, fail_token=None, existing=()):
        self.fail_token = fail_token
        self.existing = list(existing)
        self.queries = []
        self.created_tables = []
        self.dataset = types.SimpleNamespace(
            location="us-east1",
            labels={
                "environment": "shadow",
                "work_package": "wp03",
                "purpose": "compiled_sql_validation",
            },
        )

    def get_dataset(self, _dataset_id):
        return self.dataset

    def list_tables(self, _dataset):
        return list(self.existing)

    def create_table(self, table):
        self.created_tables.append(table)
        return table

    def query(self, query, job_config=None, location=None):
        self.queries.append(
            {
                "query": query,
                "dry_run": bool(getattr(job_config, "dry_run", False)),
                "location": location,
            }
        )
        if (
            getattr(job_config, "dry_run", False)
            and self.fail_token
            and self.fail_token in query
        ):
            error = RuntimeError("Name ticker is ambiguous")
            error.errors = [
                {
                    "reason": "invalidQuery",
                    "message": "Name ticker is ambiguous",
                }
            ]
            raise error
        return FakeJob()


FAKE_BIGQUERY = types.SimpleNamespace(
    SchemaField=FakeSchemaField,
    Table=FakeTable,
    QueryJobConfig=FakeQueryJobConfig,
)


class CompiledSqlPlanTests(unittest.TestCase):
    def test_plan_contains_all_outputs_and_topological_layers(self):
        plan, required, assertions = build()
        self.assertEqual(12, plan["required_output_count"])
        self.assertEqual(set(preflight.REQUIRED_OUTPUTS), set(required))
        self.assertEqual(2, len(assertions))
        flattened = [name for layer in plan["layers"] for name in layer]
        self.assertEqual(
            set(preflight.REQUIRED_OUTPUTS) - {preflight.RAW_OUTPUT},
            set(flattened),
        )
        position = {
            name: index
            for index, layer in enumerate(plan["layers"])
            for name in layer
        }
        self.assertLess(
            position["financial_quarters_pit"],
            position["financial_ttm_pit"],
        )
        self.assertLess(
            position["financial_ttm_pit"],
            position["portfolio_valuation_pit_shadow"],
        )
        self.assertRegex(plan["plan_checksum"], r"^[0-9a-f]{64}$")
        self.assertFalse(plan["production_change_allowed"])

    def test_plan_is_deterministic_and_checksum_is_enforced(self):
        first, _, _ = build()
        second, _, _ = build(list(reversed(action_fixture())))
        self.assertEqual(first["plan_checksum"], second["plan_checksum"])
        self.assertEqual(
            first["plan_checksum"],
            preflight.verify_plan_checksum(first, first["plan_checksum"]),
        )
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError, "checksum mismatch"
        ):
            preflight.verify_plan_checksum(first, "0" * 64)

    def test_missing_output_wrong_scope_and_unauthorized_dependency_fail(self):
        rows = action_fixture()[:-3]
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError, "must appear exactly once"
        ):
            build(rows)

        rows = action_fixture()
        rows[1]["target"]["schema"] = OPERATIONAL
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError, "must target"
        ):
            build(rows)

        rows = action_fixture()
        rows[2]["relation"]["dependencyTargets"].append(
            operational("secret_unapproved_table")
        )
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError, "unauthorized dependency"
        ):
            build(rows)

    def test_relation_mutation_and_operational_write_fail_closed(self):
        rows = action_fixture()
        rows[2]["relation"]["selectQuery"] = (
            f"CREATE TABLE `{PROJECT}.{VALIDATION}.bad` AS SELECT 1"
        )
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError,
            "must begin with SELECT or WITH",
        ):
            build(rows)

        rows = action_fixture()
        rows[2]["relation"]["selectQuery"] = (
            f"WITH x AS (SELECT 1) DELETE FROM "
            f"`{PROJECT}.{OPERATIONAL}.trading_price_features` WHERE TRUE"
        )
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError, "mutating SQL"
        ):
            build(rows)

        rows = action_fixture()
        rows[0]["operations"]["queries"] = [
            f"CREATE TABLE IF NOT EXISTS `{PROJECT}.other_shadow.bad` "
            "(revision_id STRING)"
        ]
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError, "must create only"
        ):
            build(rows)

    def test_actions_loader_supports_pages_and_rejects_empty_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actions.json"
            path.write_text(
                json.dumps(
                    {
                        "pages": [
                            {"compilationResultActions": action_fixture()[:6]},
                            {"compilationResultActions": action_fixture()[6:]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                len(action_fixture()),
                len(preflight.load_actions_document(path)),
            )
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(
                preflight.SemanticPreflightError,
                "compilationResultActions",
            ):
                preflight.load_actions_document(path)


class SchemaGraphExecutionTests(unittest.TestCase):
    def contract(self, directory):
        path = Path(directory) / "raw.yaml"
        path.write_text(
            """
columns:
  - name: revision_id
    type: STRING
    mode: REQUIRED
  - name: available_at
    type: TIMESTAMP
    mode: NULLABLE
""".strip()
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_complete_schema_graph_and_assertions_pass(self):
        plan, required, assertions = build()
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            result = preflight.execute_schema_graph(
                plan=plan,
                required=required,
                assertions=assertions,
                contract_path=self.contract(directory),
                location="us-east1",
                client=client,
                bigquery_module=FAKE_BIGQUERY,
            )
        self.assertEqual(
            "ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS",
            result["status"],
        )
        self.assertEqual(0, result["failed_action_count"])
        self.assertEqual(0, result["failed_assertion_count"])
        self.assertEqual(1, len(client.created_tables))
        self.assertEqual(12, len(result["created_objects"]))
        self.assertTrue(
            all(row["status"] == "PASS" for row in result["action_results"])
        )
        self.assertTrue(
            all(
                row["status"] == "PASS"
                for row in result["assertion_results"]
            )
        )
        view_queries = [
            query["query"]
            for query in client.queries
            if query["query"].startswith("CREATE OR REPLACE VIEW")
        ]
        self.assertTrue(view_queries)
        self.assertTrue(all(") WHERE FALSE" in query for query in view_queries))
        self.assertTrue(
            all(
                row.get("zero_row_guard") is True
                for row in result["created_objects"]
                if row["object_type"] == "ZERO_ROW_SCHEMA_VIEW"
            )
        )
        self.assertFalse(result["production_change_allowed"])

    def test_one_layer_failure_blocks_descendants_but_checks_independent_branch(self):
        plan, required, assertions = build(
            action_fixture(ambiguous_quarters=True)
        )
        client = FakeClient(fail_token="AMBIGUOUS")
        with tempfile.TemporaryDirectory() as directory:
            result = preflight.execute_schema_graph(
                plan=plan,
                required=required,
                assertions=assertions,
                contract_path=self.contract(directory),
                location="us-east1",
                client=client,
                bigquery_module=FAKE_BIGQUERY,
            )
        self.assertEqual("FAIL", result["status"])
        by_name = {
            row["name"]: row for row in result["action_results"]
        }
        self.assertEqual("FAIL", by_name["financial_quarters_pit"]["status"])
        self.assertEqual(
            "BLOCKED_BY_FAILED_DEPENDENCY",
            by_name["financial_ttm_pit"]["status"],
        )
        self.assertEqual("PASS", by_name["earnings_events_pit"]["status"])
        self.assertGreater(result["failed_action_count"], 0)

    def test_dataset_scope_labels_and_empty_state_are_required(self):
        plan, required, assertions = build()
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            client.dataset.labels["purpose"] = "wrong"
            with self.assertRaisesRegex(
                preflight.SemanticPreflightError, "labels are invalid"
            ):
                preflight.execute_schema_graph(
                    plan=plan,
                    required=required,
                    assertions=assertions,
                    contract_path=self.contract(directory),
                    location="us-east1",
                    client=client,
                    bigquery_module=FAKE_BIGQUERY,
                )

            client = FakeClient(existing=[types.SimpleNamespace(table_id="old")])
            with self.assertRaisesRegex(
                preflight.SemanticPreflightError, "must be empty"
            ):
                preflight.execute_schema_graph(
                    plan=plan,
                    required=required,
                    assertions=assertions,
                    contract_path=self.contract(directory),
                    location="us-east1",
                    client=client,
                    bigquery_module=FAKE_BIGQUERY,
                )

    def test_validation_dataset_name_must_be_isolated(self):
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError,
            "both 'shadow' and 'schema'",
        ):
            preflight.validate_scope(PROJECT, OPERATIONAL, "wp03_validation")
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError,
            "cannot equal",
        ):
            preflight.validate_scope(
                PROJECT,
                "acciones_dataset_shadow_schema",
                "acciones_dataset_shadow_schema",
            )


if __name__ == "__main__":
    unittest.main()
