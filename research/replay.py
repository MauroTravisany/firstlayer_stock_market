"""Validate an immutable experiment bundle and emit a read-only replay plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.common.data_snapshots import (
    SnapshotError,
    assert_publishable as assert_snapshot_publishable,
)
from packages.common.experiment_registry import ExperimentError, assert_publishable
from packages.common.hashing import (
    build_candidate_id,
    dependency_lock_hash,
    is_sha256,
    sha256_json,
)

REQUIRED = {
    "experiment",
    "snapshot",
    "candidates",
    "artifacts",
    "decisions",
    "dependency_lock_files",
}


class ReplayError(ValueError):
    """A replay cannot prove that its source inputs are identical."""


def load_manifest(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"invalid replay manifest: {path}") from exc
    if not isinstance(document, dict):
        raise ReplayError("replay manifest must be a JSON object")
    missing = sorted(REQUIRED - set(document))
    if missing:
        raise ReplayError("replay manifest missing: " + ", ".join(missing))
    return document


def _configuration(experiment: Mapping[str, Any]):
    try:
        value = json.loads(str(experiment.get("configuration_json") or ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReplayError("experiment configuration_json is invalid") from exc
    if not isinstance(value, dict) or not value:
        raise ReplayError("experiment configuration must be a non-empty object")
    if sha256_json(value) != experiment.get("configuration_hash"):
        raise ReplayError("configuration_hash mismatch")
    return value


def _validate_candidates(experiment, candidates):
    seen = set()
    for row in candidates:
        try:
            configuration = json.loads(str(row.get("configuration_json") or ""))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReplayError("candidate configuration_json is invalid") from exc
        config_hash = sha256_json(configuration)
        if config_hash != row.get("configuration_hash"):
            raise ReplayError("candidate configuration_hash mismatch")
        expected = build_candidate_id(
            str(experiment["experiment_id"]),
            str(experiment["run_id"]),
            int(row.get("generation") or 0),
            row.get("parent_candidate_id"),
            config_hash,
        )
        if expected != row.get("candidate_id"):
            raise ReplayError("candidate_id does not match canonical lineage")
        if expected in seen:
            raise ReplayError("duplicate candidate_id in replay bundle")
        seen.add(expected)


def validate_manifest(manifest: Mapping[str, Any], root: str | Path = "."):
    root = Path(root).resolve()
    experiment = manifest["experiment"]
    snapshot = manifest["snapshot"]
    candidates = list(manifest["candidates"])
    artifacts = list(manifest["artifacts"])
    decisions = list(manifest["decisions"])
    assert_snapshot_publishable(snapshot)
    assert_publishable(experiment, candidates, artifacts, decisions)
    configuration = _configuration(experiment)
    _validate_candidates(experiment, candidates)
    if experiment.get("data_snapshot_id") != snapshot.get("data_snapshot_id"):
        raise ReplayError("experiment data_snapshot_id differs from snapshot")
    if experiment.get("data_snapshot_checksum") != snapshot.get(
        "content_checksum"
    ):
        raise ReplayError("experiment snapshot checksum differs from snapshot")
    for field in (
        "data_contract_version",
        "contract_set_hash",
        "schema_snapshot_hash",
    ):
        if experiment.get(field) != snapshot.get(field):
            raise ReplayError(f"experiment and snapshot {field} differ")
    lock_files = manifest["dependency_lock_files"]
    if not isinstance(lock_files, list) or not lock_files:
        raise ReplayError("dependency_lock_files must be a non-empty list")
    observed_dependency_hash = dependency_lock_hash(
        [root / str(path) for path in lock_files], root=root
    )
    if observed_dependency_hash != experiment.get("dependency_lock_hash"):
        raise ReplayError("dependency_lock_hash does not match current files")
    identity = {
        "experiment_id": experiment["experiment_id"],
        "run_id": experiment["run_id"],
        "git_sha": experiment["git_sha"],
        "data_snapshot_id": experiment["data_snapshot_id"],
        "data_contract_version": experiment["data_contract_version"],
        "contract_set_hash": experiment["contract_set_hash"],
        "schema_snapshot_hash": experiment["schema_snapshot_hash"],
        "feature_set_version": experiment["feature_set_version"],
        "strategy_version": experiment["strategy_version"],
        "execution_model_version": experiment["execution_model_version"],
        "cost_model_version": experiment["cost_model_version"],
        "configuration_hash": experiment["configuration_hash"],
        "dependency_lock_hash": observed_dependency_hash,
        "results_checksum": experiment["results_checksum"],
        "candidate_ids": sorted(row["candidate_id"] for row in candidates),
    }
    if not is_sha256(identity["results_checksum"]):
        raise ReplayError("results_checksum must be SHA-256")
    return {
        "status": "VALIDATED",
        "mutation_performed": False,
        "configuration": configuration,
        "identity": identity,
        "replay_plan_checksum": sha256_json(identity),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate_manifest(load_manifest(args.manifest), args.root)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (
        ReplayError,
        ExperimentError,
        SnapshotError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
