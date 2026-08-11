import unittest

from packages.common import experiment_registry, hashing

EXPERIMENT_ID = "123e4567-e89b-42d3-a456-426614174000"
RUN_ID = hashing.run_id(EXPERIMENT_ID, "attempt-1")
RESULT_CONTENT = hashing.canonical_json({"candidate_results": ["ok"]})
RESULT_CHECKSUM = hashing.sha256_text(RESULT_CONTENT)


def experiment(status="COMPLETED"):
    configuration = {
        "attempt_id": "attempt-1",
        "asset_scope": "MEGACAP_TECH",
        "weights": {"trend": 1.0},
    }
    return {
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "parent_experiment_id": None,
        "created_at": "2026-08-10T00:00:00Z",
        "status": status,
        "hypothesis": "Test one bounded candidate.",
        "git_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "environment": "shadow",
        "data_snapshot_id": "snapshot_" + "1" * 64,
        "data_snapshot_checksum": "2" * 64,
        "data_contract_version": "audit-contracts-v1",
        "contract_set_hash": "3" * 64,
        "schema_snapshot_hash": "8" * 64,
        "universe_version": "megacap-tech-v1",
        "feature_set_version": "legacy-feature-set-v1",
        "strategy_version": "v2",
        "execution_model_version": "legacy-daily-v1",
        "cost_model_version": "legacy-cost-v1",
        "configuration_json": hashing.canonical_json(configuration),
        "configuration_hash": hashing.sha256_json(configuration),
        "dependency_lock_hash": "4" * 64,
        "hypothesis_count": 1,
        "production_change_allowed": False,
        "results_checksum": RESULT_CHECKSUM if status == "COMPLETED" else None,
        "completed_at": (
            "2026-08-11T00:00:00Z" if status == "COMPLETED" else None
        ),
    }


def candidate():
    configuration = {"formula_version": "v1", "weight": 1.0}
    return {
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "candidate_id": hashing.candidate_id(
            EXPERIMENT_ID, RUN_ID, 1, None, configuration
        ),
        "generation": 1,
        "hypothesis_index": 1,
        "parent_candidate_id": None,
        "candidate_status": "COMPLETED",
        "configuration_json": hashing.canonical_json(configuration),
        "configuration_hash": hashing.sha256_json(configuration),
        "production_change_allowed": False,
        "created_at": "2026-08-10T00:00:01Z",
        "completed_at": "2026-08-11T00:00:00Z",
        "result_checksum": "6" * 64,
    }


def artifact():
    return {
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "artifact_id": hashing.artifact_id(
            EXPERIMENT_ID, RUN_ID, "RESULT_SUMMARY", RESULT_CHECKSUM
        ),
        "candidate_id": None,
        "artifact_type": "RESULT_SUMMARY",
        "uri": "inline://result-summary",
        "media_type": "application/json",
        "content_json": RESULT_CONTENT,
        "checksum": RESULT_CHECKSUM,
        "size_bytes": len(RESULT_CONTENT.encode("utf-8")),
        "immutable": True,
        "created_at": "2026-08-11T00:00:00Z",
    }


def decision():
    evidence = {"verdict": "RESEARCH_ONLY"}
    return {
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


class RegistryTests(unittest.TestCase):
    def test_complete_lineage_is_publishable_but_has_no_production_authority(self):
        experiment_registry.assert_publishable(
            experiment(), [candidate()], [artifact()], [decision()]
        )

    def test_incomplete_experiment_cannot_publish(self):
        errors = experiment_registry.publication_errors(
            experiment("RUNNING"), [], [], []
        )
        self.assertIn("EXPERIMENT_NOT_COMPLETED", errors)
        self.assertIn("NO_CANDIDATES", errors)
        self.assertIn("NO_ARTIFACTS", errors)
        self.assertIn("NO_DECISIONS", errors)

    def test_run_id_is_recomputed_from_persisted_attempt_id(self):
        record = experiment()
        configuration = {
            "attempt_id": "different-attempt",
            "asset_scope": "MEGACAP_TECH",
            "weights": {"trend": 1.0},
        }
        record["configuration_json"] = hashing.canonical_json(configuration)
        record["configuration_hash"] = hashing.sha256_json(configuration)
        errors = experiment_registry.validate_experiment(record)
        self.assertIn("RUN_IDENTITY_HASH_MISMATCH", errors)

    def test_missing_attempt_id_is_rejected(self):
        record = experiment()
        configuration = {"asset_scope": "MEGACAP_TECH"}
        record["configuration_json"] = hashing.canonical_json(configuration)
        record["configuration_hash"] = hashing.sha256_json(configuration)
        errors = experiment_registry.validate_experiment(record)
        self.assertIn("MISSING_ATTEMPT_ID", errors)

    def test_candidate_from_other_run_is_rejected(self):
        row = candidate()
        row["run_id"] = hashing.run_id(EXPERIMENT_ID, "other")
        errors = experiment_registry.validate_candidate(row, experiment())
        self.assertIn("CANDIDATE_RUN_MISMATCH", errors)

    def test_artifact_and_decision_ids_are_recomputed(self):
        bad_artifact = artifact()
        bad_artifact["artifact_id"] = "artifact_" + "f" * 64
        bad_decision = decision()
        bad_decision["evidence_json"] = hashing.canonical_json({"verdict": "OTHER"})
        errors = experiment_registry.publication_errors(
            experiment(), [candidate()], [bad_artifact], [bad_decision]
        )
        self.assertIn("ARTIFACT_ID_MISMATCH", errors)
        self.assertIn("DECISION_ID_MISMATCH", errors)

    def test_duplicate_artifact_and_decision_ids_are_rejected(self):
        errors = experiment_registry.publication_errors(
            experiment(),
            [candidate()],
            [artifact(), artifact()],
            [decision(), decision()],
        )
        self.assertIn("DUPLICATE_ARTIFACT_ID", errors)
        self.assertIn("DUPLICATE_DECISION_ID", errors)

    def test_external_parent_candidate_requires_parent_experiment_lineage(self):
        parent_candidate_id = "cand_" + "9" * 64
        config = {"formula_version": "v2", "weight": 1.0}
        row = candidate()
        row.update(
            {
                "candidate_id": hashing.candidate_id(
                    EXPERIMENT_ID, RUN_ID, 2, parent_candidate_id, config
                ),
                "generation": 2,
                "parent_candidate_id": parent_candidate_id,
                "configuration_json": hashing.canonical_json(config),
                "configuration_hash": hashing.sha256_json(config),
            }
        )
        errors = experiment_registry.publication_errors(
            experiment(), [row], [artifact()], [decision()]
        )
        self.assertIn("PARENT_CANDIDATE_OUTSIDE_BUNDLE", errors)

        with_parent = experiment()
        with_parent["parent_experiment_id"] = (
            "223e4567-e89b-42d3-a456-426614174000"
        )
        errors = experiment_registry.publication_errors(
            with_parent, [row], [artifact()], [decision()]
        )
        self.assertNotIn("PARENT_CANDIDATE_OUTSIDE_BUNDLE", errors)
        self.assertNotIn("EXTERNAL_PARENT_GENERATION_INVALID", errors)

    def test_hypothesis_index_must_be_unique_and_contiguous(self):
        first = candidate()
        second = dict(first)
        config = {"formula_version": "v1", "weight": 2.0}
        second.update(
            {
                "candidate_id": hashing.candidate_id(
                    EXPERIMENT_ID, RUN_ID, 1, None, config
                ),
                "configuration_json": hashing.canonical_json(config),
                "configuration_hash": hashing.sha256_json(config),
            }
        )
        record = experiment()
        record["hypothesis_count"] = 2
        errors = experiment_registry.publication_errors(
            record, [first, second], [artifact()], [decision()]
        )
        self.assertIn("DUPLICATE_HYPOTHESIS_INDEX", errors)
