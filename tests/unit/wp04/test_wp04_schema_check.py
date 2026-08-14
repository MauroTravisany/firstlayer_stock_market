import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "tools" / "wp04_compiled_sql_schema_check.py"
spec = importlib.util.spec_from_file_location("wp04_schema_check", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

PROJECT = "stocks-437902"
OPERATIONAL = "acciones_dataset"
VALIDATION = "acciones_dataset_shadow_wp04_schema_test"
COMPILATION = "projects/stocks-437902/locations/us-east1/repositories/dataform/compilationResults/test"
SHA = "a" * 40


def target(name, schema=VALIDATION):
    return {"database": PROJECT, "schema": schema, "name": name}


def operation(name):
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
                "(id STRING)"
            ],
        },
    }


def relation(name, dependencies=(), sql="SELECT 1 AS value"):
    return {
        "target": target(name),
        "canonicalTarget": target(name, OPERATIONAL),
        "filePath": f"definitions/{name}.sqlx",
        "relation": {
            "dependencyTargets": [target(item) for item in dependencies],
            "disabled": False,
            "selectQuery": sql,
            "relationType": "TABLE",
        },
    }


def assertion(name, dependencies=(), parent=None):
    body = {
        "dependencyTargets": [target(item) for item in dependencies],
        "disabled": False,
        "selectQuery": "SELECT 1 AS violation WHERE FALSE",
    }
    if parent:
        body["parentAction"] = target(parent)
    return {
        "target": target(name),
        "canonicalTarget": target(name, OPERATIONAL),
        "filePath": f"definitions/{name}.sqlx",
        "assertion": body,
    }


def valid_actions():
    rows = [operation(name) for name in module.OPERATION_ACTIONS]
    rows.extend(
        [
            relation("price_source_reconciliation", ["market_price_raw"]),
            relation(
                "market_price_canonical",
                [
                    "market_price_raw",
                    "corporate_actions_pit",
                    "market_session_calendar",
                    "price_source_reconciliation",
                ],
            ),
            relation("fx_rates_pit", ["market_price_canonical"]),
            relation(
                "trading_price_features_canonical_shadow",
                ["market_price_canonical"],
            ),
            relation(
                "trading_price_features_wp04_shadow",
                ["trading_price_features_canonical_shadow"],
            ),
            relation(
                "wp04_legacy_vs_canonical_shadow",
                ["trading_price_features_canonical_shadow"],
            ),
            assertion(
                "audit_canonical_prices",
                [
                    "market_price_raw",
                    "corporate_actions_pit",
                    "market_session_calendar",
                    "price_source_reconciliation",
                    "market_price_canonical",
                    "fx_rates_pit",
                    "trading_price_features_canonical_shadow",
                    "wp04_legacy_vs_canonical_shadow",
                ],
            ),
            assertion(
                "market_price_canonical_assertions_uniqueKey_0",
                ["market_price_canonical"],
                parent="market_price_canonical",
            ),
        ]
    )
    return rows


class Wp04SchemaCheckTests(unittest.TestCase):
    def build(self, rows=None):
        rows = rows or valid_actions()
        document_hash = hashlib.sha256(
            json.dumps(rows, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return module.build_plan(
            rows,
            project_id=PROJECT,
            operational_dataset=OPERATIONAL,
            validation_dataset=VALIDATION,
            compilation_result=COMPILATION,
            git_sha=SHA,
            actions_document_sha256=document_hash,
        )

    def test_plan_preserves_native_action_types_and_checksum(self):
        plan, required, generated = self.build()
        self.assertEqual(10, plan["required_action_count"])
        self.assertEqual(
            {"operations": 3, "relation": 6, "assertion": 1},
            plan["required_action_type_counts"],
        )
        self.assertEqual("assertion", plan["required_action_types"]["audit_canonical_prices"])
        self.assertEqual(1, plan["required_assertion_count"])
        self.assertEqual(1, plan["generated_assertion_count"])
        self.assertEqual(set(module.REQUIRED_ACTIONS), set(required))
        self.assertEqual(1, len(generated))
        self.assertRegex(plan["plan_checksum"], r"^[0-9a-f]{64}$")
        self.assertFalse(plan["production_change_allowed"])

    def test_wrong_required_type_fails_closed(self):
        rows = valid_actions()
        rows = [row for row in rows if row["target"]["name"] != "audit_canonical_prices"]
        rows.append(relation("audit_canonical_prices"))
        with self.assertRaisesRegex(module.Wp04SchemaCheckError, "must be assertion"):
            self.build(rows)

    def test_join_using_is_rejected_before_bigquery(self):
        rows = valid_actions()
        for row in rows:
            if row["target"]["name"] == "price_source_reconciliation":
                row["relation"]["selectQuery"] = (
                    "SELECT * FROM `a` JOIN `b` USING (ticker)"
                )
        with self.assertRaisesRegex(module.Wp04SchemaCheckError, "JOIN USING"):
            self.build(rows)

    def test_operational_write_is_rejected(self):
        rows = valid_actions()
        for row in rows:
            if row["target"]["name"] == "market_price_canonical":
                row["relation"]["selectQuery"] = (
                    "CREATE TABLE `stocks-437902.acciones_dataset.bad` AS SELECT 1"
                )
        with self.assertRaises(module.Wp04SchemaCheckError):
            self.build(rows)

    def test_cli_help_is_available(self):
        result = subprocess.run(
            [sys.executable, str(PATH), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--actions-json", result.stdout)
        self.assertIn("--expected-plan-checksum", result.stdout)
        self.assertIn("WP04_SCHEMA_VALIDATION_WRITE", PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
