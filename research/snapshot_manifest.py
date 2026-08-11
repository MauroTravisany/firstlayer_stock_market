"""Build a deterministic snapshot record without mutating BigQuery."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.common.data_contracts import load_contract_directory, manifest_document
from packages.common.data_snapshots import (
    SnapshotError,
    build_snapshot_record,
    publish_snapshot,
)


def _read_json(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict) or not value:
        raise SnapshotError(f"JSON object required: {path}")
    return value


def _timestamp(value: str) -> dt.datetime:
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError("source cutoff must be ISO-8601") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise SnapshotError("source cutoff must include a timezone")
    return result


def build(
    *,
    contracts_dir: Path,
    source_manifest: Path,
    source_cutoff: str,
    environment: str,
    created_by: str,
    quality_report: Path | None = None,
    publish: bool = False,
    parent_snapshot_id: str | None = None,
):
    contract_set = load_contract_directory(contracts_dir)
    contract_manifest = manifest_document(contract_set)
    record = build_snapshot_record(
        contract_set_hash=contract_manifest["contract_set_hash"],
        schema_snapshot_hash=contract_manifest["schema_snapshot_hash"],
        source_cutoff_at=_timestamp(source_cutoff),
        source_manifest=_read_json(source_manifest),
        environment=environment,
        data_contract_version=contract_manifest["data_contract_version"],
        created_by=created_by,
        parent_snapshot_id=parent_snapshot_id,
    )
    if publish:
        if quality_report is None:
            raise SnapshotError("--publish requires --quality-report")
        record = publish_snapshot(record, _read_json(quality_report))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts-dir", type=Path, default=Path("contracts"))
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-cutoff", required=True)
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--quality-report", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--parent-snapshot-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = build(
            contracts_dir=args.contracts_dir,
            source_manifest=args.source_manifest,
            source_cutoff=args.source_cutoff,
            environment=args.environment,
            created_by=args.created_by,
            quality_report=args.quality_report,
            publish=args.publish,
            parent_snapshot_id=args.parent_snapshot_id,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (SnapshotError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "data_snapshot_id": record["data_snapshot_id"],
                "snapshot_status": record["snapshot_status"],
                "mutation_performed": False,
                "output": args.output.as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
