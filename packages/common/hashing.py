"""Canonical serialization and content-addressed identifiers for audit-grade research."""

from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
UUID_CANONICAL = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
RUN_ID = re.compile(r"^run_[0-9a-f]{64}$")
CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{64}$")
ARTIFACT_ID = re.compile(r"^artifact_[0-9a-f]{64}$")
DECISION_ID = re.compile(r"^decision_[0-9a-f]{64}$")
SNAPSHOT_ID = re.compile(r"^snapshot_[0-9a-f]{64}$")


class CanonicalizationError(ValueError):
    """A value cannot be represented by the repository's canonical JSON format."""


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("non-finite floats are not canonical")
        return 0.0 if value == 0 else value
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            raise CanonicalizationError("non-finite decimals are not canonical")
        return format(value.normalize(), "f")
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalizationError("datetime values must be timezone-aware")
        return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Path):
        return value.as_posix()
    if dataclasses.is_dataclass(value):
        return _normalize(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalizationError("mapping keys must be strings")
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        rows = [_normalize(item) for item in value]
        return sorted(rows, key=canonical_json)
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    raise CanonicalizationError(f"unsupported value type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def is_sha256(value: Any) -> bool:
    return bool(SHA256.fullmatch(str(value or "")))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_files(
    paths: Iterable[str | Path], *, root: str | Path | None = None
) -> str:
    base = Path(root).resolve() if root is not None else None
    rows = []
    for path in sorted(
        (Path(value).resolve() for value in paths), key=lambda item: item.as_posix()
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
        logical_path = path.relative_to(base).as_posix() if base else path.name
        rows.append(
            {
                "path": logical_path,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    if not rows:
        raise CanonicalizationError("at least one dependency file is required")
    return sha256_json(rows)


def dependency_lock_hash(
    paths: Iterable[str | Path], *, root: str | Path | None = None
) -> str:
    return sha256_files(paths, root=root)


def new_experiment_id() -> str:
    return str(uuid.uuid4())


def run_id(experiment_id: str, attempt_id: str) -> str:
    if not UUID_CANONICAL.fullmatch(str(experiment_id)):
        raise CanonicalizationError("experiment_id must be a canonical UUID")
    if not str(attempt_id).strip():
        raise CanonicalizationError("attempt_id is required")
    return "run_" + sha256_json(
        {"experiment_id": experiment_id, "attempt_id": str(attempt_id)}
    )


def build_run_id(experiment_id: str, attempt_id: str) -> str:
    return run_id(experiment_id, attempt_id)


def candidate_id(
    experiment_id: str,
    run_id_value: str,
    generation: int,
    parent_candidate_id: str | None,
    configuration: Mapping[str, Any] | str,
) -> str:
    if not UUID_CANONICAL.fullmatch(str(experiment_id)):
        raise CanonicalizationError("experiment_id must be a canonical UUID")
    if not RUN_ID.fullmatch(str(run_id_value)):
        raise CanonicalizationError("run_id must use run_<sha256>")
    if int(generation) < 1:
        raise CanonicalizationError("generation must be >= 1")
    if parent_candidate_id is not None and not CANDIDATE_ID.fullmatch(
        str(parent_candidate_id)
    ):
        raise CanonicalizationError("parent candidate must use cand_<sha256>")
    configuration_hash = (
        configuration if is_sha256(configuration) else sha256_json(configuration)
    )
    return "cand_" + sha256_json(
        {
            "experiment_id": experiment_id,
            "run_id": run_id_value,
            "generation": int(generation),
            "parent_candidate_id": parent_candidate_id,
            "candidate_configuration_hash": configuration_hash,
        }
    )


def build_candidate_id(
    experiment_id: str,
    run_id_value: str,
    generation: int,
    parent_candidate_id: str | None,
    candidate_configuration_hash: str,
) -> str:
    return candidate_id(
        experiment_id,
        run_id_value,
        generation,
        parent_candidate_id,
        candidate_configuration_hash,
    )


def _validate_lineage_identity(
    experiment_id: str,
    run_id_value: str,
    candidate_id_value: str | None = None,
) -> None:
    if not UUID_CANONICAL.fullmatch(str(experiment_id)):
        raise CanonicalizationError("experiment_id must be a canonical UUID")
    if not RUN_ID.fullmatch(str(run_id_value)):
        raise CanonicalizationError("run_id must use run_<sha256>")
    if candidate_id_value is not None and not CANDIDATE_ID.fullmatch(
        str(candidate_id_value)
    ):
        raise CanonicalizationError("candidate_id must use cand_<sha256>")


def artifact_id(
    experiment_id: str,
    run_id_value: str,
    artifact_type: str,
    checksum: str,
    candidate_id_value: str | None = None,
) -> str:
    _validate_lineage_identity(experiment_id, run_id_value, candidate_id_value)
    if not str(artifact_type).strip():
        raise CanonicalizationError("artifact_type is required")
    if not is_sha256(checksum):
        raise CanonicalizationError("artifact checksum must be SHA-256")
    return "artifact_" + sha256_json(
        {
            "experiment_id": experiment_id,
            "run_id": run_id_value,
            "candidate_id": candidate_id_value,
            "artifact_type": artifact_type,
            "checksum": checksum,
        }
    )


def decision_id(
    experiment_id: str,
    run_id_value: str,
    decision_type: str,
    evidence: Mapping[str, Any],
    candidate_id_value: str | None = None,
) -> str:
    _validate_lineage_identity(experiment_id, run_id_value, candidate_id_value)
    if not str(decision_type).strip():
        raise CanonicalizationError("decision_type is required")
    if not isinstance(evidence, Mapping):
        raise CanonicalizationError("decision evidence must be a mapping")
    return "decision_" + sha256_json(
        {
            "experiment_id": experiment_id,
            "run_id": run_id_value,
            "candidate_id": candidate_id_value,
            "decision_type": decision_type,
            "evidence": evidence,
        }
    )


def snapshot_id(
    data_contract_version: str,
    contract_set_hash: str,
    schema_snapshot_hash: str,
    source_manifest_hash: str,
    content_checksum: str,
) -> str:
    if not str(data_contract_version).strip():
        raise CanonicalizationError("data_contract_version is required")
    for label, digest in (
        ("contract_set_hash", contract_set_hash),
        ("schema_snapshot_hash", schema_snapshot_hash),
        ("source_manifest_hash", source_manifest_hash),
        ("content_checksum", content_checksum),
    ):
        if not is_sha256(digest):
            raise CanonicalizationError(f"{label} must be SHA-256")
    return "snapshot_" + sha256_json(
        {
            "data_contract_version": data_contract_version,
            "contract_set_hash": contract_set_hash,
            "schema_snapshot_hash": schema_snapshot_hash,
            "source_manifest_hash": source_manifest_hash,
            "content_checksum": content_checksum,
        }
    )


def build_snapshot_id(
    contract_set_hash: str,
    schema_snapshot_hash: str,
    source_cutoff_at: dt.datetime,
    source_manifest_hash: str,
) -> str:
    """Build the content-addressed identity used by the local snapshot publisher."""
    for label, digest in (
        ("contract_set_hash", contract_set_hash),
        ("schema_snapshot_hash", schema_snapshot_hash),
        ("source_manifest_hash", source_manifest_hash),
    ):
        if not is_sha256(digest):
            raise CanonicalizationError(f"{label} must be SHA-256")
    if source_cutoff_at.tzinfo is None or source_cutoff_at.utcoffset() is None:
        raise CanonicalizationError("source_cutoff_at must be timezone-aware")
    return "snapshot_" + sha256_json(
        {
            "contract_set_hash": contract_set_hash,
            "schema_snapshot_hash": schema_snapshot_hash,
            "source_cutoff_at": source_cutoff_at,
            "source_manifest_hash": source_manifest_hash,
        }
    )
