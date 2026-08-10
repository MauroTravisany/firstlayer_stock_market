"""Enforce additive Dataform expand/contract compatibility during WP-01."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DESTRUCTIVE_SQL = (
    re.compile(r"\bDROP\s+(?:TABLE|VIEW|COLUMN)\b", re.IGNORECASE),
    re.compile(r"\bRENAME\s+(?:TABLE|COLUMN|TO)\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+(?:COLUMN|TABLE)\b[^;]*\bTYPE\b", re.IGNORECASE),
    re.compile(r"\bCREATE\s+OR\s+REPLACE\b", re.IGNORECASE),
)


class CompatibilityError(RuntimeError):
    """The Dataform release violates the active expand contract."""


def _tables(document, key):
    value = document.get(key)
    if not isinstance(value, dict) or not value:
        raise CompatibilityError(f"{key} must be a non-empty object")
    normalized = {}
    for table, columns in value.items():
        if not isinstance(columns, list) or not columns or len(columns) != len(set(columns)):
            raise CompatibilityError(f"{key}.{table} must contain unique columns")
        normalized[str(table)] = {str(column) for column in columns}
    return normalized


def reject_destructive_sql(sql):
    text = str(sql)
    for pattern in DESTRUCTIVE_SQL:
        if pattern.search(text):
            raise CompatibilityError(f"destructive SQL rejected in expand release: {pattern.pattern}")
    return True


def validate_transition(previous, current):
    if not isinstance(previous, dict) or not isinstance(current, dict):
        raise CompatibilityError("compatibility manifests must be JSON objects")
    if current.get("schema_version") != 1:
        raise CompatibilityError("compatibility schema_version must equal 1")
    if current.get("phase") != "expand":
        raise CompatibilityError("WP-01 permits only an expand release")
    if current.get("destructive_changes") not in ([], None):
        raise CompatibilityError("expand releases cannot declare destructive changes")

    previous_schema = _tables(previous, "expanded_schema")
    current_schema = _tables(current, "expanded_schema")
    consumers = current.get("consumer_contracts")
    if not isinstance(consumers, dict) or set(consumers) != {"legacy", "current"}:
        raise CompatibilityError("both legacy and current consumer contracts are required")
    legacy = _tables(consumers, "legacy")
    new = _tables(consumers, "current")

    for table, columns in previous_schema.items():
        if table not in current_schema or not columns.issubset(current_schema[table]):
            raise CompatibilityError(f"expanded schema removed legacy contract from {table}")
        if table not in legacy or not columns.issubset(legacy[table]):
            raise CompatibilityError(
                f"legacy consumer contract must preserve every previously supported column in {table}"
            )

    for label, contract in (("legacy", legacy), ("current", new)):
        for table, columns in contract.items():
            if table not in current_schema or not columns.issubset(current_schema[table]):
                raise CompatibilityError(f"{label} consumer requires unavailable columns in {table}")

    return {
        "status": "PASS",
        "phase": "expand",
        "previous_release_id": previous.get("release_id"),
        "current_release_id": current.get("release_id"),
        "tables": len(current_schema),
    }


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"invalid compatibility manifest: {path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--scan", action="append", default=[])
    args = parser.parse_args()
    try:
        result = validate_transition(_read(args.previous), _read(args.current))
        for root in args.scan:
            for path in Path(root).rglob("*.sqlx"):
                reject_destructive_sql(path.read_text(encoding="utf-8"))
    except (CompatibilityError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
