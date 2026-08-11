"""Compare a read-only BigQuery schema export with repository data contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.common.data_contracts import (
    ContractError,
    compare_schema,
    load_contract_directory,
)


class SchemaSnapshotError(ValueError):
    """An observed-schema snapshot is malformed or incomplete."""


def load_observed(path: Path) -> dict[str, list[dict]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaSnapshotError(f"invalid observed schema JSON: {path}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SchemaSnapshotError(
            "observed schema snapshot must use schema_version=1"
        )
    tables = document.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise SchemaSnapshotError(
            "observed schema snapshot requires a non-empty tables object"
        )
    normalized: dict[str, list[dict]] = {}
    for name, fields in tables.items():
        if not isinstance(name, str) or not name or not isinstance(fields, list):
            raise SchemaSnapshotError(
                "observed table entries must map names to field lists"
            )
        normalized[name] = fields
    return normalized


def validate_snapshot(contracts_dir: Path, observed_path: Path) -> dict:
    contract_set = load_contract_directory(contracts_dir)
    observed = load_observed(observed_path)
    expected = {row["table"]["name"]: row for row in contract_set.contracts}
    drift: dict[str, list[str]] = {}
    for table_name, contract in sorted(expected.items()):
        if table_name not in observed:
            drift[table_name] = ["MISSING_TABLE"]
            continue
        differences = compare_schema(contract, observed[table_name])
        if differences:
            drift[table_name] = differences
    unexpected_tables = sorted(set(observed) - set(expected))
    return {
        "status": "FAIL" if drift else "PASS",
        "data_contract_version": contract_set.data_contract_version,
        "contract_set_hash": contract_set.contract_set_hash,
        "schema_snapshot_hash": contract_set.schema_snapshot_hash,
        "validated_table_count": len(expected),
        "drift": drift,
        "unmanaged_observed_tables": unexpected_tables,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts-dir", type=Path, default=Path("contracts"))
    parser.add_argument("--observed-schema", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate_snapshot(args.contracts_dir, args.observed_schema)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (ContractError, SchemaSnapshotError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
