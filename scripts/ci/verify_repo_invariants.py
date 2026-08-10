"""Fail-closed checks for repository and deployment safety invariants."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


EXPECTED_OPERATING_STATE = {
    "research": "BACKTEST_ONLY",
    "policy": "SHADOW_ONLY",
    "broker": "ALPACA_PAPER",
}
IGNORED_SCAN_PARTS = {
    ".git",
    ".evidence",
    ".terraform",
    "build",
    "node_modules",
    "__pycache__",
}
TEXT_SUFFIXES = {
    ".cjs",
    ".env",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".sqlx",
    ".tf",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    re.compile(r'"private_key"\s*:\s*"(?!<redacted>)[^"\n]{32,}"'),
)


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    path: str
    message: str


def _read(root: Path, relative: str) -> str | None:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _load_yaml(source: str) -> dict:
    document = yaml.load(source, Loader=yaml.BaseLoader)
    if not isinstance(document, dict):
        raise ValueError("workflow root must be a mapping")
    return document


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _workflow_violations(root: Path) -> Iterable[Violation]:
    relative = ".github/workflows/deploy.yml"
    source = _read(root, relative)
    if source is None:
        yield Violation("DEPLOY_WORKFLOW_MISSING", relative, "deploy workflow is required")
        return

    try:
        workflow = _load_yaml(source)
    except (ValueError, yaml.YAMLError) as exc:
        yield Violation("DEPLOY_WORKFLOW_INVALID", relative, str(exc))
        return

    triggers = workflow.get("on", {})
    if not isinstance(triggers, dict):
        triggers = {}

    trigger_text = json.dumps(triggers, sort_keys=True)
    if re.search(r'\bmaster\b', trigger_text):
        yield Violation("DEPLOY_FROM_MASTER", relative, "master is present in deploy triggers")
    if "pull_request" in triggers:
        yield Violation(
            "DEPLOY_FROM_PULL_REQUEST", relative, "pull_request must never trigger deploy"
        )
    if "push" in triggers or "workflow_dispatch" in triggers:
        yield Violation(
            "DEPLOY_DIRECT_TRIGGER",
            relative,
            "deploy must only follow the successful CI workflow_run",
        )

    workflow_run = triggers.get("workflow_run", {})
    ci_chain_valid = (
        isinstance(workflow_run, dict)
        and _as_list(workflow_run.get("workflows")) == ["CI"]
        and _as_list(workflow_run.get("types")) == ["completed"]
        and _as_list(workflow_run.get("branches")) == ["main"]
    )
    build = workflow.get("jobs", {}).get("build", {})
    condition = build.get("if", "") if isinstance(build, dict) else ""
    ci_chain_valid = ci_chain_valid and all(
        fragment in condition
        for fragment in (
            "conclusion == 'success'",
            "head_branch == 'main'",
            "event == 'push'",
        )
    )
    if not ci_chain_valid:
        yield Violation(
            "DEPLOY_WITHOUT_CI",
            relative,
            "deploy is not bound to successful CI for an exact main push",
        )

    if "strategy-brain-generate" in source or "strategy-brain-review" in source:
        yield Violation(
            "STRATEGY_BRAIN_REACTIVATION",
            relative,
            "deploy workflow must not configure paused Strategy Brain schedulers",
        )
    if re.search(r"gcloud\s+scheduler\s+jobs\s+(?:create|update|resume)", source):
        yield Violation(
            "SCHEDULER_MUTATION_IN_DEPLOY",
            relative,
            "code deploy must not mutate scheduler configuration",
        )


def _policy_violations(root: Path) -> Iterable[Violation]:
    relative = "dataform/definitions/trading_champion_challenger_policy.sqlx"
    source = _read(root, relative)
    if source is None:
        yield Violation("POLICY_MISSING", relative, "champion/challenger policy is required")
        return
    if "SHADOW_ONLY" not in source or "PAPER_CHAMPION" in source or re.search(
        r'"LIVE(?:_[A-Z]+)*"', source
    ):
        yield Violation(
            "POLICY_NOT_SHADOW_ONLY",
            relative,
            "champion/challenger policy must remain SHADOW_ONLY",
        )

    brain_relative = "cloud-functions/strategy_brain/main.py"
    brain = _read(root, brain_relative)
    if brain is None:
        yield Violation("STRATEGY_BRAIN_MISSING", brain_relative, "Strategy Brain source is required")
    elif re.search(
        r'["\']production_change_allowed["\']\s*:\s*(?:True|true)', brain
    ):
        yield Violation(
            "PRODUCTION_CHANGE_ALLOWED",
            brain_relative,
            "Strategy Brain cannot permit production changes",
        )


def _paper_mode_violations(root: Path) -> Iterable[Violation]:
    relatives = (
        "cloud-functions/paper_trade_executor/conf/conf.py",
        "cloud-functions/paper_trade_risk_monitor/conf/conf.py",
    )
    for relative in relatives:
        source = _read(root, relative)
        if source is None:
            yield Violation("PAPER_CONFIG_MISSING", relative, "Paper configuration is required")
            continue
        if (
            "paper-api.alpaca.markets" not in source
            or 'os.environ.get("PAPER_EXECUTION_MODE", "paper")' not in source
            or "api.alpaca.markets\"" in source.replace("paper-api.alpaca.markets\"", "")
        ):
            yield Violation(
                "ALPACA_NOT_PAPER_ONLY",
                relative,
                "Alpaca endpoint and execution mode must fail closed to Paper",
            )


def _legacy_violations(root: Path) -> Iterable[Violation]:
    registry_relative = "dataform/definitions/legacy_result_registry.sqlx"
    registry = _read(root, registry_relative)
    if registry is None or any(
        fragment not in (registry or "")
        for fragment in (
            "LEGACY_PRE_AUDIT_GRADE",
            "FALSE AS promotion_eligible",
            "NOT_ELIGIBLE_FOR_PROMOTION",
        )
    ):
        yield Violation(
            "LEGACY_LOCK_REMOVED",
            registry_relative,
            "static legacy classification and promotion lock must remain present",
        )

    manifest_relative = "docs/audit-grade/evidence/baseline_manifest.json"
    source = _read(root, manifest_relative)
    if source is None:
        yield Violation("BASELINE_MANIFEST_MISSING", manifest_relative, "baseline manifest is required")
        return
    try:
        manifest = json.loads(source)
    except json.JSONDecodeError as exc:
        yield Violation("BASELINE_MANIFEST_INVALID", manifest_relative, str(exc))
        return

    operating_state = manifest.get("operating_state", {})
    if any(operating_state.get(key) != value for key, value in EXPECTED_OPERATING_STATE.items()):
        yield Violation(
            "OPERATING_STATE_UNSAFE",
            manifest_relative,
            f"operating_state must equal {EXPECTED_OPERATING_STATE}",
        )

    policy = manifest.get("policy", {})
    if (
        set(policy.get("strategy_brain_statuses", [])) - {"BACKTEST_ONLY", "LEGACY_RESEARCH"}
        or set(policy.get("production_change_allowed_values", [])) != {False}
        or any(row.get("execution_mode") != "SHADOW_ONLY" for row in policy.get("rows", []))
    ):
        yield Violation(
            "BASELINE_POLICY_UNSAFE",
            manifest_relative,
            "baseline policy no longer records the safe research state",
        )

    cloud_inventory = manifest.get("cloud", manifest.get("cloud_inventory", {}))
    scheduler_states = {}
    for row in cloud_inventory.get("schedulers", []):
        name = (row.get("name") or "").rsplit("/", 1)[-1]
        if name in {"strategy-brain-generate", "strategy-brain-review"}:
            scheduler_states[name] = row.get("state")
    if scheduler_states != {
        "strategy-brain-generate": "PAUSED",
        "strategy-brain-review": "PAUSED",
    }:
        yield Violation(
            "STRATEGY_BRAIN_NOT_PAUSED",
            manifest_relative,
            "baseline must record both Strategy Brain schedulers as PAUSED",
        )

    legacy_results = manifest.get("legacy_results", [])
    if manifest.get("promotion_eligible") is not False or any(
        row.get("promotion_eligible") is not False
        or row.get("legacy_classification") != "LEGACY_PRE_AUDIT_GRADE"
        or row.get("promotion_block_reason") != "NOT_ELIGIBLE_FOR_PROMOTION"
        for row in legacy_results
    ):
        yield Violation(
            "LEGACY_PROMOTION_ENABLED",
            manifest_relative,
            "legacy results must remain non-promotable",
        )


def _candidate_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_SCAN_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", "Procfile"}:
            yield path


def _secret_violations(root: Path) -> Iterable[Violation]:
    for path in _candidate_text_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(source):
                yield Violation(
                    "HARDCODED_SECRET",
                    path.relative_to(root).as_posix(),
                    "high-confidence credential pattern detected",
                )
                break


def collect_violations(root: Path) -> list[Violation]:
    root = root.resolve()
    checks = (
        _workflow_violations,
        _policy_violations,
        _paper_mode_violations,
        _legacy_violations,
        _secret_violations,
    )
    violations = {violation for check in checks for violation in check(root)}
    return sorted(violations)


def run(root: Path) -> int:
    violations = collect_violations(root)
    if violations:
        print("REPO_INVARIANTS_INVALID")
        for violation in violations:
            print(
                json.dumps(
                    {
                        "code": violation.code,
                        "path": violation.path,
                        "message": violation.message,
                    },
                    sort_keys=True,
                )
            )
        return 2
    print("REPO_INVARIANTS_VALID")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    return run(parser.parse_args().root)


if __name__ == "__main__":
    raise SystemExit(main())
