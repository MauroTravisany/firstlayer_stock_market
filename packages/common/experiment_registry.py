"""Pure experiment-registry invariants shared by CI and replay tooling."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from .hashing import (
    ARTIFACT_ID,
    CANDIDATE_ID,
    DECISION_ID,
    GIT_SHA,
    IMAGE_DIGEST,
    RUN_ID,
    SNAPSHOT_ID,
    UUID_CANONICAL,
    artifact_id,
    candidate_id,
    canonical_json,
    decision_id,
    is_sha256,
    run_id as build_run_id,
    sha256_json,
    sha256_text,
)

TERMINAL = {"COMPLETED", "REJECTED", "FAILED", "CANCELLED"}
RUN_STATUSES = {"CREATED", "CANDIDATES_READY", "RUNNING", *TERMINAL}
CANDIDATE_STATUSES = {"CREATED", "RUNNING", "COMPLETED", "REJECTED", "FAILED"}
ENVIRONMENTS = {"research", "shadow", "paper", "staging"}


class ExperimentError(ValueError):
    """Experiment lineage is ambiguous, incomplete, or unsafe to publish."""


def _non_empty(record: Mapping[str, Any], field: str, errors: list[str]) -> None:
    if not str(record.get(field) or "").strip():
        errors.append(f"MISSING_{field.upper()}")


def _canonical_mapping(
    value: Any,
    *,
    json_field: str,
    hash_field: str,
    record: Mapping[str, Any],
    errors: list[str],
    prefix: str,
) -> Mapping[str, Any] | None:
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        errors.append(f"{prefix}_{json_field.upper()}_INVALID")
        return None
    if not isinstance(parsed, Mapping):
        errors.append(f"{prefix}_{json_field.upper()}_NOT_OBJECT")
        return None
    canonical = canonical_json(parsed)
    if canonical != str(value):
        errors.append(f"{prefix}_{json_field.upper()}_NOT_CANONICAL")
    if sha256_json(parsed) != record.get(hash_field):
        errors.append(f"{prefix}_{hash_field.upper()}_MISMATCH")
    return parsed


def validate_experiment(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not UUID_CANONICAL.fullmatch(str(record.get("experiment_id") or "")):
        errors.append("INVALID_EXPERIMENT_ID")
    if not RUN_ID.fullmatch(str(record.get("run_id") or "")):
        errors.append("INVALID_RUN_ID")
    parent = record.get("parent_experiment_id")
    if parent is not None and not UUID_CANONICAL.fullmatch(str(parent)):
        errors.append("INVALID_PARENT_EXPERIMENT_ID")
    if record.get("status") not in RUN_STATUSES:
        errors.append("INVALID_RUN_STATUS")
    if record.get("environment") not in ENVIRONMENTS:
        errors.append("INVALID_ENVIRONMENT")
    if record.get("production_change_allowed") is not False:
        errors.append("PRODUCTION_CHANGE_ALLOWED")

    for field in (
        "created_at",
        "hypothesis",
        "git_sha",
        "data_snapshot_id",
        "data_snapshot_checksum",
        "data_contract_version",
        "contract_set_hash",
        "schema_snapshot_hash",
        "universe_version",
        "feature_set_version",
        "strategy_version",
        "execution_model_version",
        "cost_model_version",
        "configuration_json",
        "configuration_hash",
        "dependency_lock_hash",
    ):
        _non_empty(record, field, errors)

    if record.get("git_sha") and not GIT_SHA.fullmatch(str(record["git_sha"])):
        errors.append("INVALID_GIT_SHA")
    if record.get("image_digest") and not IMAGE_DIGEST.fullmatch(
        str(record["image_digest"])
    ):
        errors.append("INVALID_IMAGE_DIGEST")
    if record.get("data_snapshot_id") and not SNAPSHOT_ID.fullmatch(
        str(record["data_snapshot_id"])
    ):
        errors.append("INVALID_DATA_SNAPSHOT_ID")

    configuration = _canonical_mapping(
        record.get("configuration_json"),
        json_field="configuration_json",
        hash_field="configuration_hash",
        record=record,
        errors=errors,
        prefix="EXPERIMENT",
    )
    if configuration is not None:
        attempt_id = str(configuration.get("attempt_id") or "").strip()
        if not attempt_id:
            errors.append("MISSING_ATTEMPT_ID")
        elif UUID_CANONICAL.fullmatch(str(record.get("experiment_id") or "")):
            try:
                expected_run_id = build_run_id(
                    str(record["experiment_id"]), attempt_id
                )
            except ValueError:
                errors.append("RUN_IDENTITY_INPUT_INVALID")
            else:
                if expected_run_id != record.get("run_id"):
                    errors.append("RUN_IDENTITY_HASH_MISMATCH")
    for field in (
        "configuration_hash",
        "dependency_lock_hash",
        "contract_set_hash",
        "schema_snapshot_hash",
        "data_snapshot_checksum",
    ):
        if record.get(field) and not is_sha256(record[field]):
            errors.append(f"INVALID_{field.upper()}")
    try:
        hypothesis_count = int(record.get("hypothesis_count"))
    except (TypeError, ValueError):
        hypothesis_count = 0
    if hypothesis_count < 1:
        errors.append("INVALID_HYPOTHESIS_COUNT")
    return sorted(set(errors))


def validate_candidate(
    row: Mapping[str, Any], experiment: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if row.get("experiment_id") != experiment.get("experiment_id"):
        errors.append("CANDIDATE_EXPERIMENT_MISMATCH")
    if row.get("run_id") != experiment.get("run_id"):
        errors.append("CANDIDATE_RUN_MISMATCH")
    if row.get("candidate_status") not in CANDIDATE_STATUSES:
        errors.append("INVALID_CANDIDATE_STATUS")
    if row.get("production_change_allowed") is not False:
        errors.append("CANDIDATE_PRODUCTION_CHANGE_ALLOWED")
    if not CANDIDATE_ID.fullmatch(str(row.get("candidate_id") or "")):
        errors.append("INVALID_CANDIDATE_ID")
    parent = row.get("parent_candidate_id")
    if parent is not None and not CANDIDATE_ID.fullmatch(str(parent)):
        errors.append("INVALID_PARENT_CANDIDATE_ID")
    try:
        generation = int(row.get("generation"))
    except (TypeError, ValueError):
        generation = 0
    try:
        hypothesis_index = int(row.get("hypothesis_index"))
    except (TypeError, ValueError):
        hypothesis_index = 0
    if generation < 1:
        errors.append("INVALID_CANDIDATE_GENERATION")
    if hypothesis_index < 1:
        errors.append("INVALID_HYPOTHESIS_INDEX")

    configuration = _canonical_mapping(
        row.get("configuration_json"),
        json_field="configuration_json",
        hash_field="configuration_hash",
        record=row,
        errors=errors,
        prefix="CANDIDATE",
    )
    if configuration is not None:
        try:
            expected = candidate_id(
                str(experiment.get("experiment_id")),
                str(experiment.get("run_id")),
                generation,
                parent,
                configuration,
            )
        except ValueError:
            errors.append("CANDIDATE_LINEAGE_INPUT_INVALID")
        else:
            if expected != row.get("candidate_id"):
                errors.append("CANDIDATE_LINEAGE_HASH_MISMATCH")
    return sorted(set(errors))


def _validate_artifact(
    row: Mapping[str, Any],
    experiment: Mapping[str, Any],
    candidate_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if row.get("experiment_id") != experiment.get("experiment_id") or row.get(
        "run_id"
    ) != experiment.get("run_id"):
        errors.append("ARTIFACT_LINEAGE_MISMATCH")
    candidate = row.get("candidate_id")
    if candidate is not None and candidate not in candidate_ids:
        errors.append("ARTIFACT_CANDIDATE_MISSING")
    if not ARTIFACT_ID.fullmatch(str(row.get("artifact_id") or "")):
        errors.append("INVALID_ARTIFACT_ID")
    checksum = row.get("checksum")
    if not is_sha256(checksum):
        errors.append("INVALID_ARTIFACT_CHECKSUM")
    for field in ("artifact_type", "uri", "media_type", "created_at"):
        _non_empty(row, field, errors)
    if row.get("immutable") is not True:
        errors.append("MUTABLE_ARTIFACT")

    content_json = row.get("content_json")
    if content_json is not None:
        try:
            parsed = json.loads(str(content_json))
        except (TypeError, json.JSONDecodeError):
            errors.append("ARTIFACT_CONTENT_JSON_INVALID")
        else:
            if canonical_json(parsed) != str(content_json):
                errors.append("ARTIFACT_CONTENT_JSON_NOT_CANONICAL")
            if sha256_text(str(content_json)) != checksum:
                errors.append("ARTIFACT_CONTENT_CHECKSUM_MISMATCH")
    if is_sha256(checksum):
        try:
            expected = artifact_id(
                str(experiment.get("experiment_id")),
                str(experiment.get("run_id")),
                str(row.get("artifact_type") or ""),
                str(checksum),
                candidate,
            )
        except ValueError:
            errors.append("ARTIFACT_ID_INPUT_INVALID")
        else:
            if expected != row.get("artifact_id"):
                errors.append("ARTIFACT_ID_MISMATCH")
    return sorted(set(errors))


def _validate_decision(
    row: Mapping[str, Any],
    experiment: Mapping[str, Any],
    candidate_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if row.get("experiment_id") != experiment.get("experiment_id") or row.get(
        "run_id"
    ) != experiment.get("run_id"):
        errors.append("DECISION_LINEAGE_MISMATCH")
    candidate = row.get("candidate_id")
    if candidate is not None and candidate not in candidate_ids:
        errors.append("DECISION_CANDIDATE_MISSING")
    if not DECISION_ID.fullmatch(str(row.get("decision_id") or "")):
        errors.append("INVALID_DECISION_ID")
    for field in (
        "decision_type",
        "decision_status",
        "reason_code",
        "evidence_json",
        "actor_type",
        "created_at",
    ):
        _non_empty(row, field, errors)
    if row.get("production_change_allowed") is not False:
        errors.append("DECISION_PRODUCTION_CHANGE_ALLOWED")

    try:
        evidence = json.loads(str(row.get("evidence_json") or ""))
    except (TypeError, json.JSONDecodeError):
        errors.append("DECISION_EVIDENCE_JSON_INVALID")
    else:
        if not isinstance(evidence, Mapping):
            errors.append("DECISION_EVIDENCE_NOT_OBJECT")
        else:
            if canonical_json(evidence) != str(row.get("evidence_json")):
                errors.append("DECISION_EVIDENCE_NOT_CANONICAL")
            try:
                expected = decision_id(
                    str(experiment.get("experiment_id")),
                    str(experiment.get("run_id")),
                    str(row.get("decision_type") or ""),
                    evidence,
                    candidate,
                )
            except ValueError:
                errors.append("DECISION_ID_INPUT_INVALID")
            else:
                if expected != row.get("decision_id"):
                    errors.append("DECISION_ID_MISMATCH")
    return sorted(set(errors))


def publication_errors(
    experiment: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    artifacts: Iterable[Mapping[str, Any]],
    decisions: Iterable[Mapping[str, Any]],
) -> list[str]:
    errors = validate_experiment(experiment)
    candidate_rows = list(candidates)
    artifact_rows = list(artifacts)
    decision_rows = list(decisions)

    if experiment.get("status") != "COMPLETED":
        errors.append("EXPERIMENT_NOT_COMPLETED")
    if not is_sha256(experiment.get("results_checksum")):
        errors.append("RESULTS_CHECKSUM_MISSING_OR_INVALID")
    if not experiment.get("completed_at"):
        errors.append("COMPLETED_AT_MISSING")
    if not candidate_rows:
        errors.append("NO_CANDIDATES")
    if len(candidate_rows) != int(experiment.get("hypothesis_count") or 0):
        errors.append("HYPOTHESIS_COUNT_MISMATCH")

    candidate_ids: list[str] = []
    hypothesis_indexes: list[int] = []
    generations: dict[str, int] = {}
    parent_by_candidate: dict[str, str | None] = {}
    for row in candidate_rows:
        errors.extend(validate_candidate(row, experiment))
        candidate_value = str(row.get("candidate_id") or "")
        candidate_ids.append(candidate_value)
        try:
            hypothesis_indexes.append(int(row.get("hypothesis_index")))
            generations[candidate_value] = int(row.get("generation"))
        except (TypeError, ValueError):
            pass
        parent_by_candidate[candidate_value] = row.get("parent_candidate_id")
        if row.get("candidate_status") != "COMPLETED":
            errors.append("INCOMPLETE_CANDIDATE")
        if not is_sha256(row.get("result_checksum")):
            errors.append("CANDIDATE_RESULT_CHECKSUM_INVALID")
    candidate_set = set(candidate_ids)
    if len(candidate_ids) != len(candidate_set):
        errors.append("DUPLICATE_CANDIDATE_ID")
    if len(hypothesis_indexes) != len(set(hypothesis_indexes)):
        errors.append("DUPLICATE_HYPOTHESIS_INDEX")
    if sorted(hypothesis_indexes) != list(range(1, len(candidate_rows) + 1)):
        errors.append("NON_CONTIGUOUS_HYPOTHESIS_INDEX")
    for child, parent in parent_by_candidate.items():
        if parent is None:
            continue
        if parent not in candidate_set:
            if experiment.get("parent_experiment_id") is None:
                errors.append("PARENT_CANDIDATE_OUTSIDE_BUNDLE")
            if generations.get(child, 0) <= 1:
                errors.append("EXTERNAL_PARENT_GENERATION_INVALID")
        elif generations.get(parent, 0) >= generations.get(child, 0):
            errors.append("PARENT_GENERATION_NOT_EARLIER")

    if not artifact_rows:
        errors.append("NO_ARTIFACTS")
    artifact_ids = [str(row.get("artifact_id") or "") for row in artifact_rows]
    if len(artifact_ids) != len(set(artifact_ids)):
        errors.append("DUPLICATE_ARTIFACT_ID")
    result_summary_checksums = []
    for row in artifact_rows:
        errors.extend(_validate_artifact(row, experiment, candidate_set))
        if row.get("artifact_type") == "RESULT_SUMMARY":
            result_summary_checksums.append(row.get("checksum"))
    if len(result_summary_checksums) != 1:
        errors.append("RESULT_SUMMARY_COUNT_NOT_ONE")
    elif result_summary_checksums[0] != experiment.get("results_checksum"):
        errors.append("RESULT_SUMMARY_CHECKSUM_MISMATCH")

    if not decision_rows:
        errors.append("NO_DECISIONS")
    decision_ids = [str(row.get("decision_id") or "") for row in decision_rows]
    if len(decision_ids) != len(set(decision_ids)):
        errors.append("DUPLICATE_DECISION_ID")
    for row in decision_rows:
        errors.extend(_validate_decision(row, experiment, candidate_set))
    return sorted(set(errors))


def assert_publishable(
    experiment: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    artifacts: Iterable[Mapping[str, Any]],
    decisions: Iterable[Mapping[str, Any]],
) -> None:
    errors = publication_errors(experiment, candidates, artifacts, decisions)
    if errors:
        raise ExperimentError("experiment is not publishable: " + ",".join(errors))


def bundle_checksum(
    experiment: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    artifacts: Iterable[Mapping[str, Any]],
    decisions: Iterable[Mapping[str, Any]],
) -> str:
    return sha256_json(
        {
            "experiment": dict(experiment),
            "candidates": sorted(
                (dict(row) for row in candidates),
                key=lambda row: row["candidate_id"],
            ),
            "artifacts": sorted(
                (dict(row) for row in artifacts),
                key=lambda row: row["artifact_id"],
            ),
            "decisions": sorted(
                (dict(row) for row in decisions),
                key=lambda row: row["decision_id"],
            ),
        }
    )
