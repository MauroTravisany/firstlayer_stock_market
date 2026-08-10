"""Manage Dataform candidate and production refs with compare-and-swap semantics."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PRODUCTION_REF = "refs/heads/dataform-production"
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class DataformBranchError(RuntimeError):
    """A Dataform branch transaction could not be completed exactly."""


def _require_sha(value: str, label: str) -> None:
    if not GIT_SHA.fullmatch(str(value)):
        raise DataformBranchError(f"{label} must be a full lowercase git SHA")


def _require_candidate_ref(ref: str) -> None:
    if not re.fullmatch(r"refs/heads/dataform-candidate-[0-9a-z-]+", str(ref)):
        raise DataformBranchError("candidate ref must be a dataform-candidate branch")


def create_candidate(candidate_ref, candidate_sha, read_ref, compare_and_swap):
    """Create or replace only a candidate ref; production is never touched."""
    _require_candidate_ref(candidate_ref)
    _require_sha(candidate_sha, "candidate_sha")
    previous = read_ref(candidate_ref)
    if previous == candidate_sha:
        return {"changed": False, "previous_sha": previous, "final_sha": candidate_sha}
    compare_and_swap(candidate_ref, candidate_sha, previous)
    final = read_ref(candidate_ref)
    if final != candidate_sha:
        raise DataformBranchError("candidate ref verification failed")
    return {"changed": True, "previous_sha": previous, "final_sha": final}


def promote_production(previous_sha, candidate_sha, read_ref, compare_and_swap):
    """Move production to a validated candidate only if its prior SHA still matches."""
    _require_sha(previous_sha, "previous_dataform_production_sha")
    _require_sha(candidate_sha, "candidate_sha")
    current = read_ref(PRODUCTION_REF)
    if current == candidate_sha:
        return {"changed": False, "previous_sha": previous_sha, "final_sha": current}
    if current != previous_sha:
        raise DataformBranchError("dataform-production changed concurrently")
    compare_and_swap(PRODUCTION_REF, candidate_sha, previous_sha)
    final = read_ref(PRODUCTION_REF)
    if final != candidate_sha:
        raise DataformBranchError("dataform-production promotion verification failed")
    return {"changed": True, "previous_sha": previous_sha, "final_sha": final}


def rollback_production(previous_sha, candidate_sha, read_ref, compare_and_swap):
    """Restore production exactly, while rejecting an unrelated concurrent state."""
    _require_sha(previous_sha, "previous_dataform_production_sha")
    _require_sha(candidate_sha, "candidate_sha")
    current = read_ref(PRODUCTION_REF)
    if current == previous_sha:
        return {"changed": False, "previous_sha": candidate_sha, "final_sha": current}
    if current != candidate_sha:
        raise DataformBranchError(
            "dataform-production no longer matches the candidate; rollback refused"
        )
    compare_and_swap(PRODUCTION_REF, previous_sha, candidate_sha)
    final = read_ref(PRODUCTION_REF)
    if final != previous_sha:
        raise DataformBranchError("dataform-production rollback verification failed")
    return {"changed": True, "previous_sha": candidate_sha, "final_sha": final}


def _run(command):
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DataformBranchError(f"git command failed: {detail}")
    return completed.stdout


def read_remote_ref(ref):
    output = _run(["git", "ls-remote", "--refs", "origin", ref]).strip()
    if not output:
        return None
    rows = output.splitlines()
    if len(rows) != 1:
        raise DataformBranchError(f"remote ref is ambiguous: {ref}")
    sha, returned_ref = rows[0].split("\t", 1)
    if returned_ref != ref:
        raise DataformBranchError(f"unexpected remote ref: {returned_ref}")
    _require_sha(sha, "remote_ref_sha")
    return sha


def compare_and_swap_remote(ref, new_sha, expected_sha):
    _require_sha(new_sha, "new_sha")
    lease = f"--force-with-lease={ref}:{expected_sha or ''}"
    _run(["git", "push", lease, "origin", f"{new_sha}:{ref}"])


def _write_evidence(path, operation, result, **metadata):
    document = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "status": "PASS",
        **metadata,
        **result,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    candidate = subparsers.add_parser("create-candidate")
    candidate.add_argument("--candidate-ref", required=True)
    candidate.add_argument("--candidate-sha", required=True)
    candidate.add_argument("--evidence", type=Path, required=True)
    for name in ("promote-production", "rollback-production"):
        command = subparsers.add_parser(name)
        command.add_argument("--previous-sha", required=True)
        command.add_argument("--candidate-sha", required=True)
        command.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "create-candidate":
            result = create_candidate(
                args.candidate_ref,
                args.candidate_sha,
                read_remote_ref,
                compare_and_swap_remote,
            )
            evidence = _write_evidence(
                args.evidence,
                args.operation,
                result,
                candidate_ref=args.candidate_ref,
                candidate_sha=args.candidate_sha,
            )
        else:
            function = (
                promote_production
                if args.operation == "promote-production"
                else rollback_production
            )
            result = function(
                args.previous_sha,
                args.candidate_sha,
                read_remote_ref,
                compare_and_swap_remote,
            )
            evidence = _write_evidence(
                args.evidence,
                args.operation,
                result,
                previous_dataform_production_sha=args.previous_sha,
                candidate_sha=args.candidate_sha,
                final_dataform_production_sha=result["final_sha"],
            )
    except (DataformBranchError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "operation": args.operation, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
