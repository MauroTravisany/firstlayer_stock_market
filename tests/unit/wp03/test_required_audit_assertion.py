from pathlib import Path
import tempfile
import types
import unittest

from tools import wp03_compiled_sql_semantic_preflight as preflight


ROOT = Path(__file__).resolve().parents[3]
PROJECT = "stocks-437902"
OPERATIONAL = "acciones_dataset"
VALIDATION = "acciones_dataset_shadow_wp03_schema_native_assertion"
COMPILATION = (
    "projects/stocks-437902/locations/us-east1/repositories/"
    "portfolio-valuation/compilationResults/native-assertion"
)
SHA = "a" * 40


def target(name, schema=VALIDATION):
    return {"database": PROJECT, "schema": schema, "name": name}


def operational(name):
    return target(name, OPERATIONAL)


def relation(name, dependencies=(), sql=None):
    return {
        "target": target(name),
        "canonicalTarget": target(name, OPERATIONAL),
        "filePath": f"definitions/{name}.sqlx",
        "relation": {
            "dependencyTargets": list(dependencies),
            "disabled": False,
            "selectQuery": sql or f"SELECT '{name}' AS model_name",
            "relationType": "TABLE",
        },
    }


def raw_operation():
    name = preflight.RAW_OUTPUT
    return {
        "target": target(name),
        "canonicalTarget": target(name, OPERATIONAL),
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


def required_audit_assertion():
    name = preflight.AUDIT_ASSERTION
    dependencies = [
        target("financial_quarters_pit"),
        target("financial_ttm_pit"),
        target("earnings_events_pit"),
        target("trading_earnings_context_pit"),
        target("portfolio_valuation_pit_shadow"),
    ]
    return {
        "target": target(name),
        "canonicalTarget": target(name, "assertions"),
        "filePath": f"definitions/{name}.sqlx",
        "assertion": {
            "dependencyTargets": dependencies,
            "disabled": False,
            "selectQuery": "SELECT 'AUDIT_OK' AS violation WHERE FALSE",
        },
    }


def generated_assertion(parent):
    return {
        "target": target(f"assert_{parent}"),
        "canonicalTarget": target(f"assert_{parent}", "assertions"),
        "filePath": f"definitions/{parent}.sqlx",
        "assertion": {
            "dependencyTargets": [target(parent)],
            "parentAction": target(parent),
            "disabled": False,
            "selectQuery": (
                f"SELECT * FROM `{PROJECT}.{VALIDATION}.{parent}` WHERE FALSE"
            ),
        },
    }


def native_action_fixture():
    return [
        raw_operation(),
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
        required_audit_assertion(),
        generated_assertion("financial_quarters_pit"),
    ]


def strict_build(rows=None):
    return preflight.build_plan_strict(
        rows or native_action_fixture(),
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
    total_bytes_processed = 0

    def result(self, timeout=None):
        return []


class FakeClient:
    def __init__(self):
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
        return []

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
        return FakeJob()


FAKE_BIGQUERY = types.SimpleNamespace(
    SchemaField=FakeSchemaField,
    Table=FakeTable,
    QueryJobConfig=FakeQueryJobConfig,
)


class RequiredAuditAssertionTests(unittest.TestCase):
    def contract(self, directory):
        path = Path(directory) / "raw.yaml"
        path.write_text(
            """
columns:
  - name: revision_id
    type: STRING
    mode: REQUIRED
""".strip()
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_repository_model_declares_a_native_assertion(self):
        text = (
            ROOT / "dataform" / "definitions" / "audit_no_lookahead.sqlx"
        ).read_text(encoding="utf-8")
        self.assertIn('type: "assertion"', text)
        self.assertNotIn('type: "table"', text)

    def test_strict_plan_accepts_and_preserves_required_audit_assertion(self):
        plan, required, generated = strict_build()
        audit = required[preflight.AUDIT_ASSERTION]
        self.assertEqual("assertion", audit.action_type)
        self.assertEqual(12, plan["required_action_count"])
        self.assertEqual(12, plan["required_output_count"])
        self.assertEqual(1, plan["required_assertion_count"])
        self.assertEqual(1, plan["generated_assertion_count"])
        self.assertEqual(2, plan["total_assertion_count"])
        self.assertEqual(
            {"operations": 1, "relation": 10, "assertion": 1},
            plan["required_action_type_counts"],
        )
        self.assertEqual(
            "assertion",
            plan["required_action_types"][preflight.AUDIT_ASSERTION],
        )
        audit_plan_row = next(
            row
            for row in plan["required_actions"]
            if row["target"]["name"] == preflight.AUDIT_ASSERTION
        )
        self.assertEqual("assertion", audit_plan_row["action_type"])
        self.assertNotIn(
            audit.target.key,
            {action.target.key for action in generated},
        )
        self.assertIn(
            preflight.AUDIT_ASSERTION,
            [name for layer in plan["layers"] for name in layer],
        )
        self.assertRegex(plan["plan_checksum"], r"^[0-9a-f]{64}$")

    def test_strict_operator_plan_rejects_audit_relation(self):
        rows = native_action_fixture()
        audit_index = next(
            index
            for index, row in enumerate(rows)
            if row["target"]["name"] == preflight.AUDIT_ASSERTION
        )
        rows[audit_index] = relation(
            preflight.AUDIT_ASSERTION,
            [target("financial_quarters_pit")],
        )
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError,
            "must compile as assertion",
        ):
            strict_build(rows)

    def test_required_assertion_is_executed_once_in_schema_graph(self):
        plan, required, generated = strict_build()
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            result = preflight.execute_schema_graph(
                plan=plan,
                required=required,
                assertions=generated,
                contract_path=self.contract(directory),
                location="us-east1",
                client=client,
                bigquery_module=FAKE_BIGQUERY,
            )
        self.assertEqual(
            "ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS",
            result["status"],
        )
        action_names = [row["name"] for row in result["action_results"]]
        self.assertEqual(1, action_names.count(preflight.AUDIT_ASSERTION))
        self.assertNotIn(
            f"{PROJECT}.{VALIDATION}.{preflight.AUDIT_ASSERTION}",
            {row["target"] for row in result["assertion_results"]},
        )
        self.assertEqual(1, len(result["assertion_results"]))
        self.assertEqual(12, len(result["created_objects"]))
        self.assertEqual(0, result["failed_action_count"])
        self.assertEqual(0, result["failed_assertion_count"])
        self.assertFalse(result["production_change_allowed"])


if __name__ == "__main__":
    unittest.main()
