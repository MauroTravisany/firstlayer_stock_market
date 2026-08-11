"""Immutable data-snapshot identity and publication gates."""

from __future__ import annotations

import datetime as dt
import json
from copy import deepcopy
from typing import Any, Mapping

from .hashing import (
    SNAPSHOT_ID,
    build_snapshot_id,
    canonical_json,
    is_sha256,
    sha256_json,
)

TRANSITIONS = {
    "CREATED": {"VALIDATING", "REJECTED"},
    "VALIDATING": {"PUBLISHED", "REJECTED"},
    "PUBLISHED": {"SUPERSEDED"},
    "REJECTED": set(),
    "SUPERSEDED": set(),
}
IMMUTABLE_CONTENT_FIELDS = {
    "data_snapshot_id",
    "environment",
    "data_contract_version",
    "contract_set_hash",
    "schema_snapshot_hash",
    "source_cutoff_at",
    "source_manifest_json",
    "source_manifest_hash",
    "content_checksum",
    "row_count",
    "created_at",
    "created_by",
    "production_change_allowed",
}


class SnapshotError(ValueError):
    """A snapshot cannot prove immutable, quality-gated lineage."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc(value: dt.datetime, label: str) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotError(f"{label} must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _timestamp(value: Any, label: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return _utc(value, label)
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"{label} must be ISO-8601") from exc
    return _utc(parsed, label)


def _validate_source_manifest(source_manifest: Mapping[str, Any]) -> None:
    tables = source_manifest.get("tables")
    if not isinstance(tables, list) or not tables:
        raise SnapshotError("source_manifest.tables must be a non-empty list")
    identities: set[tuple[str, str]] = set()
    for index, row in enumerate(tables):
        if not isinstance(row, Mapping):
            raise SnapshotError(
                f"source_manifest.tables[{index}] must be an object"
            )
        name = str(row.get("name") or "").strip()
        if not name:
            raise SnapshotError(
                f"source_manifest.tables[{index}].name is required"
            )
        partition = str(row.get("partition") or "ALL").strip()
        digest = str(row.get("content_sha256") or "").strip().lower()
        if not is_sha256(digest):
            raise SnapshotError(
                f"source_manifest.tables[{index}].content_sha256 must be SHA-256"
            )
        identity = (name, partition)
        if identity in identities:
            raise SnapshotError(
                f"duplicate source manifest identity: {name}/{partition}"
            )
        identities.add(identity)
        if row.get("row_count") is not None:
            try:
                row_count = int(row["row_count"])
            except (TypeError, ValueError) as exc:
                raise SnapshotError(
                    f"source_manifest.tables[{index}].row_count must be an integer"
                ) from exc
            if row_count < 0:
                raise SnapshotError(
                    f"source_manifest.tables[{index}].row_count cannot be negative"
                )


def _canonical_source_manifest(
    source_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    _validate_source_manifest(source_manifest)
    normalized = dict(source_manifest)
    normalized["tables"] = sorted(
        (dict(row) for row in source_manifest["tables"]),
        key=lambda row: (
            str(row.get("name") or ""),
            str(row.get("partition") or "ALL"),
            str(row.get("content_sha256") or ""),
        ),
    )
    return normalized


def _expected_content_checksum(
    *,
    data_snapshot_id: str,
    contract_set_hash: str,
    schema_snapshot_hash: str,
    source_cutoff_at: dt.datetime,
    source_manifest_hash: str,
) -> str:
    return sha256_json(
        {
            "data_snapshot_id": data_snapshot_id,
            "contract_set_hash": contract_set_hash,
            "schema_snapshot_hash": schema_snapshot_hash,
            "source_cutoff_at": source_cutoff_at,
            "source_manifest_hash": source_manifest_hash,
        }
    )


def build_snapshot_record(
    *,
    contract_set_hash: str,
    schema_snapshot_hash: str,
    source_cutoff_at: dt.datetime,
    source_manifest: Mapping[str, Any],
    environment: str,
    data_contract_version: str,
    created_by: str,
    parent_snapshot_id: str | None = None,
    created_at: dt.datetime | None = None,
) -> dict[str, Any]:
    if not is_sha256(contract_set_hash) or not is_sha256(schema_snapshot_hash):
        raise SnapshotError("contract and schema hashes must be SHA-256")
    cutoff = _utc(source_cutoff_at, "source_cutoff_at")
    if environment not in {"research", "shadow", "paper", "staging"}:
        raise SnapshotError(
            "snapshot environment must be research, shadow, paper or staging"
        )
    if not str(data_contract_version).strip() or not str(created_by).strip():
        raise SnapshotError("data_contract_version and created_by are required")
    if parent_snapshot_id is not None and not SNAPSHOT_ID.fullmatch(
        str(parent_snapshot_id)
    ):
        raise SnapshotError("parent_snapshot_id must use snapshot_<sha256>")
    created = _utc(created_at or utc_now(), "created_at")
    canonical_manifest = _canonical_source_manifest(source_manifest)
    source_manifest_json = canonical_json(canonical_manifest)
    source_manifest_hash = sha256_json(canonical_manifest)
    identifier = build_snapshot_id(
        contract_set_hash,
        schema_snapshot_hash,
        cutoff,
        source_manifest_hash,
    )
    content_checksum = _expected_content_checksum(
        data_snapshot_id=identifier,
        contract_set_hash=contract_set_hash,
        schema_snapshot_hash=schema_snapshot_hash,
        source_cutoff_at=cutoff,
        source_manifest_hash=source_manifest_hash,
    )
    row_counts = [
        int(row["row_count"])
        for row in canonical_manifest["tables"]
        if row.get("row_count") is not None
    ]
    return {
        "data_snapshot_id": identifier,
        "environment": environment,
        "data_contract_version": data_contract_version,
        "contract_set_hash": contract_set_hash,
        "schema_snapshot_hash": schema_snapshot_hash,
        "snapshot_status": "CREATED",
        "source_cutoff_at": cutoff.isoformat().replace("+00:00", "Z"),
        "source_manifest_json": source_manifest_json,
        "source_manifest_hash": source_manifest_hash,
        "content_checksum": content_checksum,
        "row_count": (
            sum(row_counts)
            if len(row_counts) == len(canonical_manifest["tables"])
            else None
        ),
        "quality_gate_json": canonical_json({"status": "PENDING"}),
        "quality_gate_status": "PENDING",
        "immutable": False,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "published_at": None,
        "supersedes_snapshot_id": parent_snapshot_id,
        "created_by": created_by,
        "production_change_allowed": False,
    }


def validate_identity(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not SNAPSHOT_ID.fullmatch(str(record.get("data_snapshot_id") or "")):
        errors.append("INVALID_DATA_SNAPSHOT_ID")
    if record.get("environment") not in {"research", "shadow", "paper", "staging"}:
        errors.append("INVALID_ENVIRONMENT")
    for field in ("contract_set_hash", "schema_snapshot_hash", "content_checksum"):
        if not is_sha256(record.get(field)):
            errors.append(f"INVALID_{field.upper()}")
    if record.get("production_change_allowed") is not False:
        errors.append("PRODUCTION_CHANGE_ALLOWED")
    if not str(record.get("data_contract_version") or "").strip():
        errors.append("DATA_CONTRACT_VERSION_MISSING")
    if not str(record.get("created_by") or "").strip():
        errors.append("CREATED_BY_MISSING")

    try:
        parsed_manifest = json.loads(str(record.get("source_manifest_json") or ""))
        if not isinstance(parsed_manifest, Mapping):
            raise SnapshotError("source manifest JSON root must be an object")
        canonical_manifest = _canonical_source_manifest(parsed_manifest)
        canonical_manifest_json = canonical_json(canonical_manifest)
        if canonical_manifest_json != str(record.get("source_manifest_json")):
            errors.append("SOURCE_MANIFEST_JSON_NOT_CANONICAL")
        manifest_hash = sha256_json(canonical_manifest)
    except (TypeError, json.JSONDecodeError, SnapshotError, ValueError):
        manifest_hash = ""
        errors.append("SOURCE_MANIFEST_JSON_INVALID")

    if manifest_hash:
        if manifest_hash != record.get("source_manifest_hash"):
            errors.append("SOURCE_MANIFEST_HASH_MISMATCH")
        try:
            cutoff = _timestamp(record.get("source_cutoff_at"), "source_cutoff_at")
            expected_id = build_snapshot_id(
                str(record.get("contract_set_hash")),
                str(record.get("schema_snapshot_hash")),
                cutoff,
                manifest_hash,
            )
            if expected_id != record.get("data_snapshot_id"):
                errors.append("DATA_SNAPSHOT_ID_MISMATCH")
            expected_checksum = _expected_content_checksum(
                data_snapshot_id=expected_id,
                contract_set_hash=str(record.get("contract_set_hash")),
                schema_snapshot_hash=str(record.get("schema_snapshot_hash")),
                source_cutoff_at=cutoff,
                source_manifest_hash=manifest_hash,
            )
            if expected_checksum != record.get("content_checksum"):
                errors.append("CONTENT_CHECKSUM_MISMATCH")
        except (SnapshotError, ValueError):
            errors.append("DATA_SNAPSHOT_ID_INPUT_INVALID")
    return sorted(set(errors))


def transition_snapshot(
    record: Mapping[str, Any], new_status: str, **updates: Any
) -> dict[str, Any]:
    current = str(record.get("snapshot_status") or "")
    if current not in TRANSITIONS or new_status not in TRANSITIONS[current]:
        raise SnapshotError(f"invalid snapshot transition {current} -> {new_status}")
    result = deepcopy(dict(record))
    result.update(updates)
    result["snapshot_status"] = new_status
    if result.get("production_change_allowed") is not False:
        raise SnapshotError("production_change_allowed must remain false")
    if current == "PUBLISHED":
        changed = [
            field
            for field in IMMUTABLE_CONTENT_FIELDS
            if result.get(field) != record.get(field)
        ]
        if changed:
            raise SnapshotError(
                "published snapshot content cannot change: "
                + ",".join(sorted(changed))
            )
    if new_status == "PUBLISHED":
        if result.get("quality_gate_status") != "PASS":
            raise SnapshotError("PUBLISHED requires quality_gate_status=PASS")
        if validate_identity(result):
            raise SnapshotError("PUBLISHED requires a valid snapshot identity")
        result["immutable"] = True
        published = result.get("published_at") or utc_now()
        result["published_at"] = _timestamp(
            published, "published_at"
        ).isoformat().replace("+00:00", "Z")
    return result


def publish_snapshot(
    record: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    *,
    published_at=None,
) -> dict[str, Any]:
    if not isinstance(quality_report, Mapping):
        raise SnapshotError("quality_report must be a mapping")
    status = str(quality_report.get("status") or "").upper()
    normalized_report = dict(quality_report)
    normalized_report["status"] = status
    validating = transition_snapshot(
        record,
        "VALIDATING",
        quality_gate_json=canonical_json(normalized_report),
        quality_gate_status=status,
    )
    if published_at is not None:
        validating["published_at"] = _utc(published_at, "published_at")
    return transition_snapshot(validating, "PUBLISHED")


def assert_publishable(record: Mapping[str, Any]) -> None:
    errors = validate_identity(record)
    if record.get("snapshot_status") != "PUBLISHED":
        errors.append("SNAPSHOT_NOT_PUBLISHED")
    if record.get("quality_gate_status") != "PASS":
        errors.append("QUALITY_GATE_NOT_PASS")
    if record.get("immutable") is not True:
        errors.append("SNAPSHOT_NOT_IMMUTABLE")
    if not record.get("published_at"):
        errors.append("PUBLISHED_AT_MISSING")
    try:
        quality = json.loads(str(record.get("quality_gate_json") or ""))
    except (TypeError, json.JSONDecodeError):
        errors.append("QUALITY_GATE_JSON_INVALID")
    else:
        if not isinstance(quality, Mapping) or quality.get("status") != "PASS":
            errors.append("QUALITY_GATE_EVIDENCE_NOT_PASS")
        elif canonical_json(quality) != str(record.get("quality_gate_json")):
            errors.append("QUALITY_GATE_JSON_NOT_CANONICAL")
    if errors:
        raise SnapshotError(
            "snapshot is not replayable: " + ",".join(sorted(set(errors)))
        )
