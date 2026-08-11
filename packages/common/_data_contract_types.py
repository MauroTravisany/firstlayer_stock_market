"""Shared data-contract types and normalization helpers."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]{2,127}$")
COLUMN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TYPE_NAME = re.compile(
    r"^(?:STRING|BYTES|BOOL|BOOLEAN|INT64|INTEGER|FLOAT64|FLOAT|NUMERIC|"
    r"BIGNUMERIC|DATE|DATETIME|TIME|TIMESTAMP|GEOGRAPHY|JSON|ARRAY<[^>]+>)$"
)
ALLOWED_MODES = {"REQUIRED", "NULLABLE", "REPEATED"}
ALLOWED_CRITICALITY = {"P0", "P1", "P2"}
ALLOWED_ENVIRONMENTS = {"dev", "test", "research", "shadow", "paper", "staging", "production"}
ALLOWED_PIT = {"BACKTEST_ELIGIBLE", "NOT_BACKTEST_ELIGIBLE", "REGISTRY_ONLY"}
IMPLEMENTATION_MODES = {"DATAFORM_CREATE", "DATAFORM_ALTER", "CODE_SCHEMA_REFERENCE"}
REQUIRED_TOP_LEVEL = {
    "contract_version",
    "data_contract_version",
    "criticality",
    "environments",
    "point_in_time",
    "table",
    "temporal",
    "source",
    "deduplication",
    "retention",
    "columns",
    "assertions",
    "implementation",
    "producers",
    "consumers",
}


class ContractError(ValueError):
    """A contract or observed schema violates an audit-grade invariant."""


@dataclasses.dataclass(frozen=True)
class ContractSet:
    contracts: tuple[dict[str, Any], ...]
    data_contract_version: str
    contract_set_hash: str
    schema_snapshot_hash: str

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(contract["table"]["name"] for contract in self.contracts)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _strings(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "possibly empty" if allow_empty else "non-empty"
        raise ContractError(f"{label} must be a {qualifier} list")
    rows = [_text(item, label) for item in value]
    if len(rows) != len(set(rows)):
        raise ContractError(f"{label} contains duplicates")
    return rows


def normalize_type(value: str) -> str:
    aliases = {"BOOLEAN": "BOOL", "INTEGER": "INT64", "FLOAT": "FLOAT64"}
    normalized = str(value).upper().replace(" ", "")
    return aliases.get(normalized, normalized)


def normalize_shape(data_type: str, mode: str) -> tuple[str, str]:
    normalized_type = normalize_type(data_type)
    normalized_mode = str(mode or "NULLABLE").upper()
    match = re.fullmatch(r"ARRAY<(.+)>", normalized_type)
    if match:
        return normalize_type(match.group(1)), "REPEATED"
    return normalized_type, normalized_mode


def _normalize_unique(value: Any, label: str) -> list[list[str]]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{label} must be a non-empty list")
    if all(isinstance(item, str) for item in value):
        return [_strings(value, label)]
    groups = []
    for index, item in enumerate(value):
        groups.append(_strings(item, f"{label}[{index}]"))
    return groups
