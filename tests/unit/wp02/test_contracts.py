import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from packages.common import data_contracts


class ContractTests(unittest.TestCase):
    maxDiff = None

    def test_repository_contracts_load_and_manifest_is_stable(self):
        root = Path(__file__).resolve().parents[3]
        first = data_contracts.load_contract_directory(root / "contracts")
        second = data_contracts.load_contract_directory(root / "contracts")
        self.assertGreaterEqual(len(first.contracts), 12)
        self.assertEqual(first.contract_set_hash, second.contract_set_hash)
        self.assertEqual(first.schema_snapshot_hash, second.schema_snapshot_hash)
        observed = json.loads((root / "contracts/manifest.json").read_text())
        expected = data_contracts.manifest_document(first)
        self.assertEqual(len(observed["contracts"]), len(first.contracts))
        self.assertEqual(observed, expected)

    def test_schema_drift_fails_for_missing_changed_and_extra_columns(self):
        root = Path(__file__).resolve().parents[3]
        contract = data_contracts.load_contract(
            root / "contracts/audit_experiment_runs.yaml"
        )
        actual = [
            {"name": row["name"], "type": row["type"], "mode": row["mode"]}
            for row in contract["columns"]
        ]
        self.assertEqual(data_contracts.compare_schema(contract, actual), [])
        missing = [row for row in actual if row["name"] != "run_id"]
        self.assertIn(
            "MISSING_COLUMN:run_id",
            data_contracts.compare_schema(contract, missing),
        )
        changed = copy.deepcopy(actual)
        next(
            row for row in changed if row["name"] == "hypothesis_count"
        )["type"] = "STRING"
        self.assertTrue(
            any(
                value.startswith("COLUMN_SHAPE:hypothesis_count")
                for value in data_contracts.compare_schema(contract, changed)
            )
        )
        extra = actual + [
            {"name": "unexpected", "type": "STRING", "mode": "NULLABLE"}
        ]
        self.assertIn(
            "UNEXPECTED_COLUMN:unexpected",
            data_contracts.compare_schema(contract, extra),
        )

    def test_backtest_eligible_contract_cannot_use_event_time_as_availability_without_proof(self):
        root = Path(__file__).resolve().parents[3]
        document = yaml.safe_load(
            (root / "contracts/financial_statements.yaml").read_text()
        )
        document["point_in_time"] = {
            "eligibility": "BACKTEST_ELIGIBLE",
            "reason": "invalid fixture",
        }
        document["temporal"]["event_time"] = "loaded_at"
        document["temporal"]["available_at"] = "loaded_at"
        with self.assertRaises(data_contracts.ContractError):
            data_contracts.validate_contract(document)

    def test_implementation_validator_requires_all_declared_columns(self):
        root = Path(__file__).resolve().parents[3]
        contract = data_contracts.load_contract(
            root / "contracts/audit_experiment_decisions.yaml"
        )
        with tempfile.TemporaryDirectory() as directory:
            fake_root = Path(directory)
            target = fake_root / contract["implementation"]["dataform_definition"]
            target.parent.mkdir(parents=True)
            target.write_text(
                "config { type: 'operations' }\n"
                "CREATE TABLE IF NOT EXISTS ${self()} (experiment_id STRING);\n"
            )
            problems = data_contracts.validate_implementation(contract, fake_root)
        self.assertTrue(
            any("MISSING_IMPLEMENTATION_COLUMN" in value for value in problems)
        )
