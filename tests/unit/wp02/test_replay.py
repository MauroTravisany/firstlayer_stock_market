import datetime as dt
import tempfile
import unittest
from pathlib import Path

from packages.common import data_snapshots as snapshots, hashing
from research import replay

EXPERIMENT_ID = "123e4567-e89b-42d3-a456-426614174000"
RUN_ID = hashing.run_id(EXPERIMENT_ID, "attempt-1")


class ReplayTests(unittest.TestCase):
    def bundle(self, root: Path):
        lock = root / "requirements.txt"
        lock.write_text("package==1.0\n", encoding="utf-8")
        dependency_hash = hashing.sha256_files([lock], root=root)
        snapshot = snapshots.build_snapshot_record(
            environment="shadow",
            data_contract_version="audit-contracts-v1",
            contract_set_hash="a" * 64,
            schema_snapshot_hash="b" * 64,
            source_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            source_manifest={
                "tables": [{"name": "prices", "content_sha256": "9" * 64}]
            },
            created_by="unit-test",
            created_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
        )
        snapshot = snapshots.publish_snapshot(
            snapshot,
            {"status": "PASS"},
            published_at=dt.datetime(2026, 8, 11, tzinfo=dt.timezone.utc),
        )
        configuration = {"attempt_id": "attempt-1", "asset_scope": "MEGACAP_TECH"}
        candidate_configuration = {"formula_version": "v2", "weight": 1.0}
        candidate_value = hashing.candidate_id(
            EXPERIMENT_ID, RUN_ID, 1, None, candidate_configuration
        )
        candidate = {
            "experiment_id": EXPERIMENT_ID,
            "run_id": RUN_ID,
            "candidate_id": candidate_value,
            "generation": 1,
            "hypothesis_index": 1,
            "parent_candidate_id": None,
            "candidate_status": "COMPLETED",
            "configuration_json": hashing.canonical_json(candidate_configuration),
            "configuration_hash": hashing.sha256_json(candidate_configuration),
            "production_change_allowed": False,
            "created_at": "2026-08-10T00:00:01Z",
            "completed_at": "2026-08-11T00:00:00Z",
            "result_checksum": "c" * 64,
        }
        result_content = hashing.canonical_json(
            {"candidate_results": [{"candidate_id": candidate_value}]}
        )
        result_checksum = hashing.sha256_text(result_content)
        artifact = {
            "experiment_id": EXPERIMENT_ID,
            "run_id": RUN_ID,
            "artifact_id": hashing.artifact_id(
                EXPERIMENT_ID, RUN_ID, "RESULT_SUMMARY", result_checksum
            ),
            "candidate_id": None,
            "artifact_type": "RESULT_SUMMARY",
            "uri": "inline://result-summary",
            "media_type": "application/json",
            "content_json": result_content,
            "checksum": result_checksum,
            "size_bytes": len(result_content.encode("utf-8")),
            "immutable": True,
            "created_at": "2026-08-11T00:00:00Z",
        }
        evidence = {"verdict": "RESEARCH_ONLY"}
        decision = {
            "experiment_id": EXPERIMENT_ID,
            "run_id": RUN_ID,
            "decision_id": hashing.decision_id(
                EXPERIMENT_ID, RUN_ID, "MECHANICAL_REVIEW", evidence
            ),
            "candidate_id": None,
            "decision_type": "MECHANICAL_REVIEW",
            "decision_status": "RECORDED",
            "reason_code": "RESEARCH_ONLY",
            "evidence_json": hashing.canonical_json(evidence),
            "actor_type": "SYSTEM",
            "actor_id": "unit-test",
            "production_change_allowed": False,
            "created_at": "2026-08-11T00:00:00Z",
        }
        experiment = {
            "experiment_id": EXPERIMENT_ID,
            "run_id": RUN_ID,
            "parent_experiment_id": None,
            "created_at": "2026-08-10T00:00:00Z",
            "status": "COMPLETED",
            "hypothesis": "Replay one bounded candidate.",
            "git_sha": "e" * 40,
            "image_digest": "sha256:" + "a" * 64,
            "environment": "shadow",
            "data_snapshot_id": snapshot["data_snapshot_id"],
            "data_snapshot_checksum": snapshot["content_checksum"],
            "data_contract_version": snapshot["data_contract_version"],
            "contract_set_hash": snapshot["contract_set_hash"],
            "schema_snapshot_hash": snapshot["schema_snapshot_hash"],
            "universe_version": "megacap-tech-v1",
            "feature_set_version": "legacy-feature-set-v1",
            "strategy_version": "v2",
            "execution_model_version": "legacy-daily-v1",
            "cost_model_version": "legacy-cost-v1",
            "configuration_json": hashing.canonical_json(configuration),
            "configuration_hash": hashing.sha256_json(configuration),
            "dependency_lock_hash": dependency_hash,
            "hypothesis_count": 1,
            "production_change_allowed": False,
            "results_checksum": result_checksum,
            "completed_at": "2026-08-11T00:00:00Z",
        }
        return {
            "experiment": experiment,
            "snapshot": snapshot,
            "candidates": [candidate],
            "artifacts": [artifact],
            "decisions": [decision],
            "dependency_lock_files": ["requirements.txt"],
        }

    def test_replay_is_deterministic_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.bundle(root)
            first = replay.validate_manifest(bundle, root)
            second = replay.validate_manifest(bundle, root)
        self.assertEqual(
            first["replay_plan_checksum"], second["replay_plan_checksum"]
        )
        self.assertFalse(first["mutation_performed"])

    def test_dependency_change_blocks_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.bundle(root)
            (root / "requirements.txt").write_text("package==2.0\n")
            with self.assertRaises(replay.ReplayError):
                replay.validate_manifest(bundle, root)

    def test_snapshot_schema_hash_mismatch_blocks_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.bundle(root)
            bundle["experiment"]["schema_snapshot_hash"] = "0" * 64
            with self.assertRaises(replay.ReplayError):
                replay.validate_manifest(bundle, root)
