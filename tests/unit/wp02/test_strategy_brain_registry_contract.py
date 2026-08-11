import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from packages.common import hashing

ROOT = Path(__file__).resolve().parents[3]
BRAIN = ROOT / "cloud-functions" / "strategy_brain"


@unittest.skipUnless(
    (BRAIN / "experiment_identity.py").is_file(),
    "Strategy Brain runtime files not present in isolated unit fixture",
)
class StrategyBrainRegistryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(BRAIN))
        spec = importlib.util.spec_from_file_location(
            "wp02_experiment_identity", BRAIN / "experiment_identity.py"
        )
        cls.identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.identity)
        adapter_spec = importlib.util.spec_from_file_location(
            "wp02_experiment_registry_adapter",
            BRAIN / "experiment_registry_adapter.py",
        )
        cls.adapter = importlib.util.module_from_spec(adapter_spec)
        adapter_spec.loader.exec_module(cls.adapter)

    @classmethod
    def tearDownClass(cls):
        if sys.path and sys.path[0] == str(BRAIN):
            sys.path.pop(0)

    def test_runtime_and_common_canonical_hashes_match(self):
        value = {"b": [2, 1], "a": {"x": 3}}
        self.assertEqual(
            self.identity.canonical_json(value), hashing.canonical_json(value)
        )
        self.assertEqual(
            self.identity.sha256_value(value), hashing.sha256_json(value)
        )

    def test_hashed_ids_do_not_break_initial_baseline_selection(self):
        baseline = {
            "candidate_id": "cand_" + "a" * 64,
            "candidate_label": "Control sin cambio",
        }
        other = {
            "candidate_id": "cand_" + "b" * 64,
            "candidate_label": "Aumentar tendencia",
        }
        self.assertIs(self.adapter._baseline_reference([other, baseline]), baseline)
        with self.assertRaises(self.adapter.RegistryAdapterError):
            self.adapter._baseline_reference([other])

    def test_runtime_and_common_snapshot_identity_match(self):
        import datetime as dt

        contract_hash = "a" * 64
        schema_hash = "b" * 64
        source_hash = "c" * 64
        cutoff = dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc)
        self.assertEqual(
            self.identity.build_snapshot_id(
                contract_hash, schema_hash, cutoff, source_hash
            ),
            hashing.build_snapshot_id(
                contract_hash, schema_hash, cutoff, source_hash
            ),
        )

    def test_runtime_and_replay_dependency_hashes_use_the_same_logical_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "cloud-functions" / "strategy_brain" / "requirements.txt"
            path.parent.mkdir(parents=True)
            path.write_text("google-cloud-bigquery==3.0.0\n", encoding="utf-8")
            runtime_hash = self.identity.dependency_lock_hash(path)
            replay_hash = hashing.dependency_lock_hash([path], root=root)
        self.assertEqual(runtime_hash, replay_hash)

    def test_runtime_and_common_result_identities_match(self):
        experiment_id = "123e4567-e89b-42d3-a456-426614174000"
        run_id = hashing.run_id(experiment_id, "attempt-1")
        checksum = "c" * 64
        evidence = {"verdict": "RESEARCH_ONLY"}
        runtime_artifact = "artifact_" + self.identity.sha256_value(
            {
                "experiment_id": experiment_id,
                "run_id": run_id,
                "candidate_id": None,
                "artifact_type": "RESULT_SUMMARY",
                "checksum": checksum,
            }
        )
        runtime_decision = "decision_" + self.identity.sha256_value(
            {
                "experiment_id": experiment_id,
                "run_id": run_id,
                "candidate_id": None,
                "decision_type": "MECHANICAL_REVIEW",
                "evidence": evidence,
            }
        )
        self.assertEqual(
            runtime_artifact,
            hashing.artifact_id(
                experiment_id, run_id, "RESULT_SUMMARY", checksum, None
            ),
        )
        self.assertEqual(
            runtime_decision,
            hashing.decision_id(
                experiment_id, run_id, "MECHANICAL_REVIEW", evidence, None
            ),
        )

    def test_experiment_id_exists_before_candidate_identity(self):
        experiment_id = "123e4567-e89b-42d3-a456-426614174000"
        run_id = "run_" + "a" * 64
        configuration = {
            field: (1.0 if field.endswith("_weight") else "value")
            for field in self.identity.CANDIDATE_CONFIGURATION_FIELDS
        }
        configuration.update(
            {
                "training_start": "2019-01-01",
                "training_end": "2024-12-31",
                "validation_start": "2025-01-01",
                "validation_end": "2026-08-10",
                "formula_version": "v2",
                "asset_scope": "MEGACAP_TECH",
                "asset_tickers": ["AAPL", "META"],
                "target_strategy_version": "v2",
            }
        )
        candidate = self.identity.build_candidate_id(
            experiment_id, run_id, 1, None, configuration
        )
        self.assertRegex(candidate, self.identity.CANDIDATE_ID)
        with self.assertRaises(self.identity.RegistryAdapterError):
            self.identity.build_candidate_id("", run_id, 1, None, configuration)
