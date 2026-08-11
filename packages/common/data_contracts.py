"""Strict machine-readable data contracts and deterministic schema manifests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .hashing import canonical_json, sha256_json
from ._data_contract_types import ContractError, ContractSet, normalize_shape
from ._data_contract_validate import validate_contract


def load_contract(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"could not read contract {path}: {exc}") from exc
    return validate_contract(document, source=path.as_posix())


def load_contract_directory(directory: str | Path) -> ContractSet:
    directory = Path(directory)
    paths = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
    if not paths:
        raise ContractError(f"no contracts found in {directory}")
    contracts = tuple(load_contract(path) for path in paths)
    names = [row["table"]["name"] for row in contracts]
    if len(names) != len(set(names)):
        raise ContractError("contract directory contains duplicate table names")
    versions = {row["data_contract_version"] for row in contracts}
    if len(versions) != 1:
        raise ContractError(
            f"all contracts must share one data_contract_version: {sorted(versions)}"
        )
    digest_rows = [
        {"table": row["table"]["name"], "contract_hash": row["contract_hash"]}
        for row in sorted(contracts, key=lambda value: value["table"]["name"])
    ]
    schema_rows = [
        {
            "table": row["table"]["name"],
            "logical_primary_key": row["table"]["logical_primary_key"],
            "temporal": {
                key: row["temporal"][key]
                for key in ("event_time", "available_at", "ingested_at")
            },
            "point_in_time": row["point_in_time"],
            "columns": [
                {key: column[key] for key in ("name", "type", "mode")}
                for column in row["columns"]
            ],
        }
        for row in sorted(contracts, key=lambda value: value["table"]["name"])
    ]
    return ContractSet(
        contracts=contracts,
        data_contract_version=next(iter(versions)),
        contract_set_hash=sha256_json(digest_rows),
        schema_snapshot_hash=sha256_json(schema_rows),
    )


def compare_schema(
    contract: Mapping[str, Any],
    actual_schema: Iterable[Mapping[str, Any]],
    *,
    allow_extra_columns: bool | None = None,
) -> list[str]:
    expected = {
        row["name"]: normalize_shape(row["type"], row["mode"])
        for row in contract["columns"]
    }
    actual: dict[str, tuple[str, str]] = {}
    for row in actual_schema:
        name = str(row.get("name") or "")
        if not name or name in actual:
            raise ContractError("actual schema contains missing or duplicate column names")
        actual[name] = normalize_shape(
            str(row.get("type") or row.get("field_type") or ""),
            str(row.get("mode") or "NULLABLE"),
        )
    drift = []
    for name, shape in expected.items():
        if name not in actual:
            drift.append(f"MISSING_COLUMN:{name}")
        elif actual[name] != shape:
            drift.append(
                f"COLUMN_SHAPE:{name}:expected={shape[0]}/{shape[1]}:"
                f"actual={actual[name][0]}/{actual[name][1]}"
            )
    allow_extra = (
        bool(contract.get("implementation", {}).get("allow_additional_columns", False))
        if allow_extra_columns is None
        else allow_extra_columns
    )
    if not allow_extra:
        drift.extend(
            f"UNEXPECTED_COLUMN:{name}" for name in sorted(set(actual) - set(expected))
        )
    return sorted(drift)


def validate_implementation(
    contract: Mapping[str, Any], repo_root: str | Path
) -> list[str]:
    root = Path(repo_root)
    implementation = contract["implementation"]
    paths: list[Path] = []
    definition = implementation.get("dataform_definition")
    if definition:
        paths.append(root / definition)
    paths.extend(root / value for value in implementation.get("source_files", []))
    problems = []
    sources = []
    for path in dict.fromkeys(paths):
        if not path.is_file():
            problems.append(
                f"MISSING_IMPLEMENTATION:{path.relative_to(root).as_posix()}"
            )
        else:
            sources.append(path.read_text(encoding="utf-8"))
    if problems:
        return sorted(problems)
    combined = "\n".join(sources)
    mode = implementation["mode"]
    definition_source = (
        (root / definition).read_text(encoding="utf-8") if definition else ""
    )
    if mode == "DATAFORM_CREATE":
        if (
            "CREATE TABLE IF NOT EXISTS" not in definition_source
            or "${self()}" not in definition_source
        ):
            problems.append(
                f"INVALID_IMPLEMENTATION:{definition}:expected_additive_create"
            )
    if mode == "DATAFORM_ALTER":
        if (
            "ALTER TABLE" not in definition_source
            or "ADD COLUMN IF NOT EXISTS" not in definition_source
        ):
            problems.append(
                f"INVALID_IMPLEMENTATION:{definition}:expected_additive_alter"
            )
    for name in implementation["managed_columns"]:
        if not re.search(rf"\b{re.escape(name)}\b", combined):
            problems.append(
                f"MISSING_IMPLEMENTATION_COLUMN:{contract['table']['name']}:{name}"
            )
    return sorted(problems)


def manifest_document(contract_set: ContractSet) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "data_contract_version": contract_set.data_contract_version,
        "contract_set_hash": contract_set.contract_set_hash,
        "schema_snapshot_hash": contract_set.schema_snapshot_hash,
        "contracts": [
            {
                "table": row["table"]["name"],
                "contract_version": row["contract_version"],
                "contract_hash": row["contract_hash"],
                "criticality": row["criticality"],
                "point_in_time_eligibility": row["point_in_time"]["eligibility"],
            }
            for row in sorted(
                contract_set.contracts, key=lambda value: value["table"]["name"]
            )
        ],
    }


def contract_summary(contract_set: ContractSet) -> str:
    return canonical_json(
        {
            "status": "PASS",
            "contract_count": len(contract_set.contracts),
            "tables": list(contract_set.tables),
            "data_contract_version": contract_set.data_contract_version,
            "contract_set_hash": contract_set.contract_set_hash,
            "schema_snapshot_hash": contract_set.schema_snapshot_hash,
        }
    )
