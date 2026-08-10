"""Capture and restore complete Cloud Run traffic maps."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class TrafficRestoreError(RuntimeError):
    """One or more services could not be restored exactly."""


def _copy_traffic(value, label):
    if not isinstance(value, list):
        raise TrafficRestoreError(f"{label} must be a list")
    rows = []
    for row in value:
        if not isinstance(row, dict):
            raise TrafficRestoreError(f"{label} contains a non-object row")
        rows.append(dict(row))
    return rows


def capture_snapshot(service, document):
    if not isinstance(document, dict):
        raise TrafficRestoreError("Cloud Run service description must be an object")
    spec_traffic = _copy_traffic(document.get("spec", {}).get("traffic", []), "spec.traffic")
    status = document.get("status", {})
    status_traffic = _copy_traffic(status.get("traffic", []), "status.traffic")
    if not status_traffic:
        raise TrafficRestoreError("status.traffic cannot be empty")
    revisions = sorted(
        {str(row.get("revisionName")) for row in status_traffic if row.get("revisionName")}
    )
    percentages = {
        revision: max(
            int(row.get("percent", 0) or 0)
            for row in status_traffic
            if row.get("revisionName") == revision
        )
        for revision in revisions
    }
    tags = {
        str(row["tag"]): str(row["revisionName"])
        for row in status_traffic
        if row.get("tag") and row.get("revisionName")
    }
    return {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "spec_traffic": spec_traffic,
        "status_traffic": status_traffic,
        "revisions": revisions,
        "percentages": percentages,
        "tags": tags,
        "latest_ready_revision": status.get("latestReadyRevisionName"),
        "latest_created_revision": status.get("latestCreatedRevisionName"),
    }


def semantic_traffic(rows):
    return sorted(
        (
            str(row.get("revisionName", "")),
            int(row.get("percent", 0) or 0),
            str(row.get("tag", "")),
        )
        for row in rows
    )


def build_restore_plan(snapshot, project, region):
    service = snapshot["service"]
    rows = snapshot["status_traffic"]
    percentages = {}
    tags = []
    for row in rows:
        revision = row.get("revisionName")
        if not revision:
            raise TrafficRestoreError("traffic row is missing revisionName")
        percent = int(row.get("percent", 0) or 0)
        percentages[revision] = max(percentages.get(revision, 0), percent)
        if row.get("tag"):
            tags.append((row["tag"], revision))
    active = [(revision, percent) for revision, percent in percentages.items() if percent > 0]
    if sum(percent for _, percent in active) != 100:
        raise TrafficRestoreError("saved active traffic percentages must total 100")
    base = [
        "gcloud",
        "run",
        "services",
        "update-traffic",
        service,
        "--project",
        project,
        "--region",
        region,
        "--platform",
        "managed",
    ]
    plan = [base + ["--clear-tags", "--quiet"]]
    revisions = ",".join(f"{revision}={percent}" for revision, percent in active)
    plan.append(base + ["--to-revisions", revisions, "--quiet"])
    if tags:
        rendered_tags = ",".join(f"{tag}={revision}" for tag, revision in tags)
        plan.append(base + ["--set-tags", rendered_tags, "--quiet"])
    return plan


def restore_snapshot(snapshot, current_document, runner, project="project", region="region"):
    current_rows = current_document.get("status", {}).get("traffic", [])
    if semantic_traffic(current_rows) == semantic_traffic(snapshot["status_traffic"]):
        return False
    for command in build_restore_plan(snapshot, project, region):
        runner(command)
    return True


def restore_many(snapshots, current_documents, runner, project, region):
    failures = []
    for snapshot in reversed(snapshots):
        service = snapshot["service"]
        try:
            restore_snapshot(
                snapshot, current_documents[service], runner, project, region
            )
        except Exception as exc:
            failures.append(f"{service}: {exc}")
    if failures:
        raise TrafficRestoreError("; ".join(failures))


def _run(command, timeout=120):
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=timeout
    )
    if completed.returncode != 0:
        raise TrafficRestoreError(
            f"command failed ({completed.returncode}): {' '.join(command[:5])}"
        )
    return completed.stdout


def _describe(service, project, region):
    raw = _run(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service,
            "--project",
            project,
            "--region",
            region,
            "--platform",
            "managed",
            "--format=json",
        ]
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TrafficRestoreError("gcloud service description is not JSON") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--service", required=True)
    snapshot.add_argument("--project", required=True)
    snapshot.add_argument("--region", required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    restore = subparsers.add_parser("restore-directory")
    restore.add_argument("--directory", type=Path, required=True)
    restore.add_argument("--project", required=True)
    restore.add_argument("--region", required=True)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            result = capture_snapshot(
                args.service, _describe(args.service, args.project, args.region)
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        else:
            snapshots = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(args.directory.glob("*.json"))
            ]
            if not snapshots:
                raise TrafficRestoreError("no traffic snapshots found")
            current = {
                row["service"]: _describe(row["service"], args.project, args.region)
                for row in snapshots
            }
            restore_many(snapshots, current, _run, args.project, args.region)
    except (TrafficRestoreError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", "operation": args.command}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
