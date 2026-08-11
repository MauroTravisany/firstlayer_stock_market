import json
import tempfile
import unittest
from pathlib import Path

from packages.common.data_contracts import load_contract_directory
from scripts.ci import validate_observed_schemas

ROOT = Path(__file__).resolve().parents[3]


class ObservedSchemaCliTests(unittest.TestCase):
    def observed(self):
        contract_set = load_contract_directory(ROOT / "contracts")
        return {
            "schema_version": 1,
            "tables": {
                row["table"]["name"]: [
                    {
                        "name": column["name"],
                        "type": column["type"],
                        "mode": column["mode"],
                    }
                    for column in row["columns"]
                ]
                for row in contract_set.contracts
            },
        }

    def test_exact_schema_export_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observed.json"
            path.write_text(json.dumps(self.observed()), encoding="utf-8")
            result = validate_observed_schemas.validate_snapshot(
                ROOT / "contracts", path
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["drift"], {})

    def test_missing_table_and_changed_column_fail(self):
        observed = self.observed()
        observed["tables"].pop("audit_experiment_decisions")
        run_fields = observed["tables"]["audit_experiment_runs"]
        next(
            row for row in run_fields if row["name"] == "hypothesis_count"
        )["type"] = "STRING"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observed.json"
            path.write_text(json.dumps(observed), encoding="utf-8")
            result = validate_observed_schemas.validate_snapshot(
                ROOT / "contracts", path
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            result["drift"]["audit_experiment_decisions"], ["MISSING_TABLE"]
        )
        self.assertTrue(
            any(
                value.startswith("COLUMN_SHAPE:hypothesis_count")
                for value in result["drift"]["audit_experiment_runs"]
            )
        )


if __name__ == "__main__":
    unittest.main()
