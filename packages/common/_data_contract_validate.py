"""Structural validation for machine-readable data contracts."""

from __future__ import annotations

from typing import Any, Mapping

from .hashing import sha256_json
from ._data_contract_types import (
    ALLOWED_CRITICALITY,
    ALLOWED_ENVIRONMENTS,
    ALLOWED_MODES,
    ALLOWED_PIT,
    COLUMN_NAME,
    IMPLEMENTATION_MODES,
    REQUIRED_TOP_LEVEL,
    TABLE_NAME,
    TYPE_NAME,
    ContractError,
    _normalize_unique,
    _strings,
    _text,
    normalize_type,
)


def validate_contract(
    document: Mapping[str, Any], *, source: str = "<memory>"
) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise ContractError(f"{source}: root must be a mapping")
    missing = sorted(REQUIRED_TOP_LEVEL - set(document))
    if missing:
        raise ContractError(f"{source}: missing top-level keys: {', '.join(missing)}")

    contract_version = _text(
        str(document["contract_version"]), f"{source}.contract_version"
    )
    data_contract_version = _text(
        document["data_contract_version"], f"{source}.data_contract_version"
    )
    criticality = _text(document["criticality"], f"{source}.criticality").upper()
    if criticality not in ALLOWED_CRITICALITY:
        raise ContractError(
            f"{source}.criticality must be one of {sorted(ALLOWED_CRITICALITY)}"
        )
    environments = _strings(document["environments"], f"{source}.environments")
    invalid = sorted(set(environments) - ALLOWED_ENVIRONMENTS)
    if invalid:
        raise ContractError(f"{source}.environments contains invalid values: {invalid}")

    point_in_time = document["point_in_time"]
    if not isinstance(point_in_time, Mapping):
        raise ContractError(f"{source}.point_in_time must be a mapping")
    eligibility = _text(
        point_in_time.get("eligibility"), f"{source}.point_in_time.eligibility"
    )
    if eligibility not in ALLOWED_PIT:
        raise ContractError(
            f"{source}.point_in_time.eligibility must be one of {sorted(ALLOWED_PIT)}"
        )
    _text(point_in_time.get("reason"), f"{source}.point_in_time.reason")

    table = document["table"]
    if not isinstance(table, Mapping):
        raise ContractError(f"{source}.table must be a mapping")
    table_name = _text(table.get("name"), f"{source}.table.name")
    if not TABLE_NAME.fullmatch(table_name):
        raise ContractError(f"{source}.table.name must be lower snake_case")
    for field in ("description", "granularity", "corporate_actions_policy"):
        _text(table.get(field), f"{source}.table.{field}")
    primary_key = _strings(
        table.get("logical_primary_key"), f"{source}.table.logical_primary_key"
    )
    if not isinstance(table.get("append_only"), bool):
        raise ContractError(f"{source}.table.append_only must be boolean")
    cluster_by = _strings(
        table.get("cluster_by", []), f"{source}.table.cluster_by", allow_empty=True
    )
    partition_by = table.get("partition_by")
    if partition_by is not None:
        _text(partition_by, f"{source}.table.partition_by")

    raw_columns = document["columns"]
    if not isinstance(raw_columns, list) or not raw_columns:
        raise ContractError(f"{source}.columns must be a non-empty list")
    columns: list[dict[str, Any]] = []
    column_map: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_columns):
        label = f"{source}.columns[{index}]"
        if not isinstance(raw, Mapping):
            raise ContractError(f"{label} must be a mapping")
        required = {"name", "type", "mode", "description"}
        absent = sorted(required - set(raw))
        if absent:
            raise ContractError(f"{label} missing: {', '.join(absent)}")
        name = _text(raw["name"], f"{label}.name")
        if not COLUMN_NAME.fullmatch(name) or name in column_map:
            raise ContractError(f"{label}.name is invalid or duplicated")
        data_type = normalize_type(_text(raw["type"], f"{label}.type"))
        if not TYPE_NAME.fullmatch(data_type):
            raise ContractError(f"{label}.type is unsupported: {data_type}")
        mode = _text(raw["mode"], f"{label}.mode").upper()
        if mode not in ALLOWED_MODES:
            raise ContractError(
                f"{label}.mode must be one of {sorted(ALLOWED_MODES)}"
            )
        _text(raw["description"], f"{label}.description")
        normalized = {**dict(raw), "name": name, "type": data_type, "mode": mode}
        columns.append(normalized)
        column_map[name] = normalized

    for name in primary_key:
        if name not in column_map:
            raise ContractError(
                f"{source}: primary key references missing column {name}"
            )
        if column_map[name]["mode"] != "REQUIRED":
            raise ContractError(
                f"{source}: primary key column {name} must be REQUIRED"
            )
    for name in cluster_by:
        if name not in column_map:
            raise ContractError(
                f"{source}: cluster_by references missing column {name}"
            )

    temporal = document["temporal"]
    required_temporal = {
        "event_time",
        "available_at",
        "ingested_at",
        "timezone",
        "point_in_time_policy",
    }
    if not isinstance(temporal, Mapping) or not required_temporal.issubset(temporal):
        raise ContractError(
            f"{source}.temporal must declare {sorted(required_temporal)}"
        )
    if temporal["timezone"] != "UTC":
        raise ContractError(f"{source}.temporal.timezone must be UTC")
    _text(
        temporal["point_in_time_policy"],
        f"{source}.temporal.point_in_time_policy",
    )
    for semantic in ("event_time", "available_at", "ingested_at"):
        name = _text(temporal[semantic], f"{source}.temporal.{semantic}")
        if name not in column_map:
            raise ContractError(
                f"{source}.temporal.{semantic} references missing column {name}"
            )
        if column_map[name]["type"] != "TIMESTAMP":
            raise ContractError(
                f"{source}.temporal.{semantic} must reference TIMESTAMP"
            )
    if eligibility == "BACKTEST_ELIGIBLE":
        available = column_map[temporal["available_at"]]
        if available["mode"] != "REQUIRED":
            raise ContractError(
                f"{source}: BACKTEST_ELIGIBLE available_at must be REQUIRED"
            )
        if (
            temporal["available_at"] == temporal["event_time"]
            and not point_in_time.get("event_time_is_publication_time", False)
        ):
            raise ContractError(
                f"{source}: event_time cannot stand in for availability without explicit proof"
            )

    for field in ("source", "deduplication", "retention", "implementation"):
        if not isinstance(document[field], Mapping) or not document[field]:
            raise ContractError(f"{source}.{field} must be a non-empty mapping")
    for field in ("system", "version_field", "original_timezone"):
        _text(document["source"].get(field), f"{source}.source.{field}")
    _text(document["deduplication"].get("rule"), f"{source}.deduplication.rule")
    _text(document["retention"].get("policy"), f"{source}.retention.policy")
    _strings(document["producers"], f"{source}.producers")
    _strings(document["consumers"], f"{source}.consumers")

    assertions = document["assertions"]
    if not isinstance(assertions, Mapping):
        raise ContractError(f"{source}.assertions must be a mapping")
    not_null = _strings(
        assertions.get("not_null"), f"{source}.assertions.not_null"
    )
    unknown_not_null = sorted(set(not_null) - set(column_map))
    if unknown_not_null:
        raise ContractError(
            f"{source}: not_null references missing columns {unknown_not_null}"
        )
    required_columns = {
        row["name"] for row in columns if row["mode"] == "REQUIRED"
    }
    if not required_columns.issubset(not_null):
        raise ContractError(
            f"{source}: not_null missing required columns "
            f"{sorted(required_columns - set(not_null))}"
        )
    unique_groups = _normalize_unique(
        assertions.get("unique"), f"{source}.assertions.unique"
    )
    for group in unique_groups:
        unknown = sorted(set(group) - set(column_map))
        if unknown:
            raise ContractError(
                f"{source}: unique references missing columns {unknown}"
            )
    if primary_key not in unique_groups:
        raise ContractError(
            f"{source}: logical primary key must appear in unique assertions"
        )
    accepted_values = assertions.get("accepted_values", {})
    if not isinstance(accepted_values, Mapping):
        raise ContractError(
            f"{source}.assertions.accepted_values must be a mapping"
        )
    for name, values in accepted_values.items():
        if name not in column_map or not isinstance(values, list) or not values:
            raise ContractError(f"{source}: invalid accepted_values for {name}")

    implementation = dict(document["implementation"])
    mode = _text(implementation.get("mode"), f"{source}.implementation.mode")
    if mode not in IMPLEMENTATION_MODES:
        raise ContractError(
            f"{source}.implementation.mode must be one of "
            f"{sorted(IMPLEMENTATION_MODES)}"
        )
    definition = implementation.get("dataform_definition")
    source_files = implementation.get("source_files", [])
    if source_files:
        source_files = _strings(
            source_files, f"{source}.implementation.source_files"
        )
    if mode in {"DATAFORM_CREATE", "DATAFORM_ALTER"}:
        definition = _text(
            definition, f"{source}.implementation.dataform_definition"
        )
        if not definition.startswith("dataform/definitions/") or not definition.endswith(
            ".sqlx"
        ):
            raise ContractError(
                f"{source}: dataform_definition must point to a SQLX file"
            )
    elif not source_files:
        raise ContractError(
            f"{source}: CODE_SCHEMA_REFERENCE requires source_files"
        )
    managed_columns = implementation.get("managed_columns")
    if managed_columns is None:
        managed_columns = [row["name"] for row in columns]
    else:
        managed_columns = _strings(
            managed_columns, f"{source}.implementation.managed_columns"
        )
        unknown = sorted(set(managed_columns) - set(column_map))
        if unknown:
            raise ContractError(f"{source}: managed_columns unknown: {unknown}")
    if mode == "DATAFORM_CREATE" and set(managed_columns) != set(column_map):
        raise ContractError(
            f"{source}: DATAFORM_CREATE must manage every contract column"
        )
    implementation.update(
        {
            "mode": mode,
            "dataform_definition": definition,
            "source_files": source_files,
            "managed_columns": managed_columns,
        }
    )

    normalized = dict(document)
    normalized.update(
        {
            "contract_version": contract_version,
            "data_contract_version": data_contract_version,
            "criticality": criticality,
            "environments": environments,
            "table": {
                **dict(table),
                "name": table_name,
                "logical_primary_key": primary_key,
                "cluster_by": cluster_by,
            },
            "columns": columns,
            "assertions": {
                **dict(assertions),
                "not_null": not_null,
                "unique": unique_groups,
                "accepted_values": dict(accepted_values),
            },
            "implementation": implementation,
        }
    )
    normalized["contract_hash"] = sha256_json(
        {key: value for key, value in normalized.items() if key != "contract_hash"}
    )
    return normalized
