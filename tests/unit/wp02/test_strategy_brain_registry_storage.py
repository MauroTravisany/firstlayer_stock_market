import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BRAIN = ROOT / "cloud-functions" / "strategy_brain"


@unittest.skipUnless(
    (BRAIN / "experiment_registry_storage.py").is_file(),
    "Strategy Brain registry storage is not present in isolated staging",
)
class StrategyBrainRegistryStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in (
            "_experiment_registry_storage_core",
            "_experiment_registry_storage_candidates",
            "_experiment_registry_storage_results",
            "experiment_registry_storage",
            "experiment_identity",
        ):
            sys.modules.pop(name, None)
        sys.path.insert(0, str(BRAIN))
        for name in ("experiment_identity", "experiment_registry_storage"):
            spec = importlib.util.spec_from_file_location(name, BRAIN / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        cls.identity = sys.modules["experiment_identity"]
        cls.storage = sys.modules["experiment_registry_storage"]

    @classmethod
    def tearDownClass(cls):
        for name in (
            "_experiment_registry_storage_core",
            "_experiment_registry_storage_candidates",
            "_experiment_registry_storage_results",
            "experiment_registry_storage",
            "experiment_identity",
        ):
            sys.modules.pop(name, None)
        if sys.path and sys.path[0] == str(BRAIN):
            sys.path.pop(0)

    def context(self, run_suffix="a"):
        return {
            "experiment_id": "123e4567-e89b-42d3-a456-426614174000",
            "run_id": "run_" + run_suffix * 64,
            "parent_experiment_id": None,
            "created_at": "2026-08-11T00:00:00+00:00",
            "hypothesis": "A falsifiable registry hypothesis",
            "git_sha": "b" * 40,
            "image_digest": "sha256:" + "c" * 64,
            "dataform_compilation_id": "compilation-1",
            "environment": "shadow",
            "data_contract_version": "audit-contracts-v1",
            "contract_set_hash": "d" * 64,
            "schema_snapshot_hash": "e" * 64,
            "data_snapshot_id": "snapshot_" + "f" * 64,
            "data_snapshot_checksum": "1" * 64,
            "universe_version": "megacap-tech-v1",
            "feature_set_version": "legacy-feature-set-v1",
            "strategy_version": "v2",
            "execution_model_version": "legacy-daily-v1",
            "cost_model_version": "legacy-cost-v1",
            "configuration": {
                "training_start": "2019-01-01",
                "training_end": "2024-12-31",
                "validation_start": "2025-01-01",
                "validation_end": "2026-08-10",
            },
            "configuration_json": "{}",
            "configuration_hash": "2" * 64,
            "dependency_lock_hash": "3" * 64,
            "random_seed": 7,
            "hypothesis_count": 2,
        }

    def candidate_record(self):
        record = {
            field: 1.0
            for field in self.identity.CANDIDATE_CONFIGURATION_FIELDS
            if field.endswith("_weight")
        }
        record.update(
            {
                "run_id": "legacy-placeholder",
                "candidate_id": "legacy-placeholder",
                "candidate_status": "BACKTEST_ONLY",
                "formula_version": "brain-group-context-v2",
                "candidate_label": "fixture",
                "candidate_reason": "fixture",
                "training_start": "2019-01-01",
                "training_end": "2024-12-31",
                "validation_start": "2025-01-01",
                "validation_end": "2026-08-10",
                "min_trade_score_add": 0.0,
                "position_size_multiplier": 1.0,
                "formula_expression": "fixture",
                "created_at": "2026-08-11T00:00:00+00:00",
                "generation": 1,
                "parent_candidate_id": None,
                "asset_scope": "MEGACAP_TECH",
                "asset_tickers": ["AAPL", "META"],
                "target_strategy_version": "v2",
            }
        )
        return record

    def test_candidate_ids_are_isolated_by_run_before_activation(self):
        first = self.storage.rewrite_candidate_rows(
            [self.candidate_record()], self.context("a")
        )[0]
        second = self.storage.rewrite_candidate_rows(
            [self.candidate_record()], self.context("4")
        )[0]
        self.assertNotEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(first["candidate_status"], "REGISTRY_PENDING")
        self.assertFalse(first["production_change_allowed"])
        self.assertEqual(first["hypothesis_index"], 1)

    def test_snapshot_must_match_every_contract_hash_and_safety_gate(self):
        context = self.context()
        source_manifest = {
            "tables": [
                {
                    "name": "prices",
                    "partition": "2026-08-10",
                    "content_sha256": "4" * 64,
                }
            ]
        }
        source_hash = self.identity.sha256_value(source_manifest)
        source_cutoff = "2026-08-10T23:59:59+00:00"
        snapshot_id = self.identity.build_snapshot_id(
            context["contract_set_hash"],
            context["schema_snapshot_hash"],
            source_cutoff,
            source_hash,
        )
        checksum = self.identity.snapshot_content_checksum(
            snapshot_id,
            context["contract_set_hash"],
            context["schema_snapshot_hash"],
            source_cutoff,
            source_hash,
        )
        context["data_snapshot_id"] = snapshot_id
        context["data_snapshot_checksum"] = checksum
        row = {
            "data_snapshot_id": snapshot_id,
            "snapshot_status": "PUBLISHED",
            "quality_gate_status": "PASS",
            "quality_gate_json": self.identity.canonical_json({"status": "PASS"}),
            "immutable": True,
            "production_change_allowed": False,
            "data_contract_version": context["data_contract_version"],
            "contract_set_hash": context["contract_set_hash"],
            "schema_snapshot_hash": context["schema_snapshot_hash"],
            "source_cutoff_at": source_cutoff,
            "source_manifest_json": self.identity.canonical_json(source_manifest),
            "source_manifest_hash": source_hash,
            "content_checksum": checksum,
        }
        self.assertEqual(self.storage.validate_snapshot_row(row, context), checksum)

        invalid_schema = dict(row, schema_snapshot_hash="0" * 64)
        with self.assertRaises(self.identity.RegistryAdapterError):
            self.storage.validate_snapshot_row(invalid_schema, context)

        invalid_checksum = dict(row, content_checksum="5" * 64)
        with self.assertRaises(self.identity.RegistryAdapterError):
            self.storage.validate_snapshot_row(invalid_checksum, context)

    def test_inserted_experiment_contains_schema_hash_and_failure_field(self):
        class Client:
            def __init__(self):
                self.rows = None

            def insert_rows_json(self, table, rows, row_ids=None):
                self.rows = (table, rows, row_ids)
                return []

        client = Client()
        context = self.context()
        self.storage._insert_experiment(
            client, {"audit_runs_table": "dataset.audit_experiment_runs"}, context
        )
        row = client.rows[1][0]
        self.assertEqual(row["schema_snapshot_hash"], context["schema_snapshot_hash"])
        self.assertIsNone(row["failure_reason"])
        self.assertFalse(row["production_change_allowed"])

    def test_legacy_extensions_include_schema_lineage_and_candidate_guard(self):
        config = {
            "runs_table": "dataset.trading_brain_runs",
            "candidates_table": "dataset.trading_brain_weight_candidates",
            "audits_table": "dataset.trading_brain_ai_audits",
        }
        ddl = "\n".join(self.storage._table_ddl_extensions(config))
        self.assertIn("schema_snapshot_hash STRING", ddl)
        self.assertIn("production_change_allowed BOOL", ddl)
        self.assertIn("experiment_id STRING", ddl)


if __name__ == "__main__":
    unittest.main()
