"""Fail closed unless a successful CI run belongs to the current main SHA."""

from __future__ import annotations

import argparse
import json
import re


GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class SourceVerificationError(RuntimeError):
    """The workflow source is not eligible for deployment."""


def validate_workflow_source(
    *,
    event_name,
    conclusion,
    workflow_event,
    head_branch,
    head_repository,
    repository,
    head_sha,
    current_main_sha,
):
    checks = {
        "event_name": (event_name, "workflow_run"),
        "conclusion": (conclusion, "success"),
        "workflow_event": (workflow_event, "push"),
        "head_branch": (head_branch, "main"),
        "head_repository": (head_repository, repository),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise SourceVerificationError(
                f"{label} must be {expected!r}, received {actual!r}"
            )
    if not GIT_SHA.fullmatch(str(head_sha)):
        raise SourceVerificationError("workflow head SHA is not a full lowercase git SHA")
    if not GIT_SHA.fullmatch(str(current_main_sha)):
        raise SourceVerificationError("current main SHA is not a full lowercase git SHA")
    if head_sha != current_main_sha:
        raise SourceVerificationError(
            f"stale workflow SHA {head_sha}; current main is {current_main_sha}"
        )
    return head_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "event-name",
        "conclusion",
        "workflow-event",
        "head-branch",
        "head-repository",
        "repository",
        "head-sha",
        "current-main-sha",
    ):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    try:
        sha = validate_workflow_source(**vars(args))
    except SourceVerificationError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", "head_sha": sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
