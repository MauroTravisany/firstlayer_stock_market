"""Reject mutable GitHub Action and Docker action references."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
ACTION = re.compile(r"^[^/@\s]+/[^@\s]+@[0-9a-f]{40}$")
DOCKER = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")


def find_violations(workflows_dir):
    violations = []
    paths = sorted(Path(workflows_dir).glob("*.yml")) + sorted(
        Path(workflows_dir).glob("*.yaml")
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for match in USES.finditer(source):
            value = match.group(1)
            if value.startswith("./"):
                continue
            valid = DOCKER.fullmatch(value) if value.startswith("docker://") else ACTION.fullmatch(value)
            if not valid:
                line = source.count("\n", 0, match.start()) + 1
                violations.append(f"{path.name}:{line}: mutable action reference {value}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflows", type=Path, default=Path(".github/workflows"))
    args = parser.parse_args()
    violations = find_violations(args.workflows)
    if violations:
        print(json.dumps({"status": "FAIL", "violations": violations}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", "workflows": str(args.workflows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
