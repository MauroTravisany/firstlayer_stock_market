"""Validate and record an exact-SHA Dataform release promotion."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
COMPILATION_NAME = re.compile(
    r"^projects/[^/]+/locations/[^/]+/repositories/[^/]+/compilationResults/[^/]+$"
)


class DataformPromotionError(RuntimeError):
    """The Dataform release cannot be proven to match the approved source."""


def _require_sha(value, label):
    if not GIT_SHA.fullmatch(str(value)):
        raise DataformPromotionError(f"{label} must be a full lowercase git SHA")


def validate_compilation(document, expected_snapshot_commit):
    if not isinstance(document, dict):
        raise DataformPromotionError("compilation response must be an object")
    name = document.get("name")
    if not COMPILATION_NAME.fullmatch(str(name)):
        raise DataformPromotionError("compilation response has no valid name")
    errors = document.get("compilationErrors", [])
    if not isinstance(errors, list):
        raise DataformPromotionError("compilationErrors must be a list")
    if errors:
        raise DataformPromotionError(
            f"Dataform compilation contains {len(errors)} error(s)"
        )
    if document.get("resolvedGitCommitSha") != expected_snapshot_commit:
        raise DataformPromotionError(
            "compiled Dataform commit does not match the exact promoted snapshot"
        )
    if not document.get("releaseConfig"):
        raise DataformPromotionError(
            "compilation must be created from the production release config"
        )
    return name


def validate_release(document, expected_compilation):
    if not isinstance(document, dict):
        raise DataformPromotionError("release response must be an object")
    if document.get("gitCommitish") != "dataform-production":
        raise DataformPromotionError(
            "production release must remain bound to dataform-production"
        )
    if document.get("releaseCompilationResult") != expected_compilation:
        raise DataformPromotionError(
            "production release does not point to the validated compilation"
        )
    return document


def build_evidence(
    *,
    git_sha,
    tree_sha,
    snapshot_commit_sha,
    compilation,
    previous_release,
    current_release,
):
    for value, label in (
        (git_sha, "git_sha"),
        (tree_sha, "dataform_tree_sha"),
        (snapshot_commit_sha, "snapshot_commit_sha"),
    ):
        _require_sha(value, label)
    previous_required = {"name", "gitCommitish", "releaseCompilationResult"}
    if not isinstance(previous_release, dict) or not previous_required.issubset(
        previous_release
    ):
        raise DataformPromotionError(
            "previous release is missing mandatory rollback metadata"
        )
    compilation_name = validate_compilation(compilation, snapshot_commit_sha)
    validate_release(current_release, compilation_name)
    return {
        "status": "PASS",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "dataform_tree_sha": tree_sha,
        "snapshot_commit_sha": snapshot_commit_sha,
        "compilation_id": compilation_name,
        "release_previous": previous_release,
        "release_new": current_release,
        "rollback": {
            "release_name": previous_release["name"],
            "git_commitish": previous_release["gitCommitish"],
            "release_compilation_result": previous_release[
                "releaseCompilationResult"
            ],
        },
    }


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataformPromotionError(f"invalid JSON file: {path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--tree-sha", required=True)
    parser.add_argument("--snapshot-commit-sha", required=True)
    parser.add_argument("--compilation-json", required=True)
    parser.add_argument("--previous-release-json", required=True)
    parser.add_argument("--current-release-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = build_evidence(
            git_sha=args.git_sha,
            tree_sha=args.tree_sha,
            snapshot_commit_sha=args.snapshot_commit_sha,
            compilation=_read_json(args.compilation_json),
            previous_release=_read_json(args.previous_release_json),
            current_release=_read_json(args.current_release_json),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (DataformPromotionError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
