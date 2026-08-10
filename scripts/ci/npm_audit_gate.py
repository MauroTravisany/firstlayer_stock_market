"""Fail closed on critical npm findings except exact, unexpired exceptions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path


ADVISORY_ID = re.compile(r"^(?:GHSA-[0-9a-z-]+|CVE-\d{4}-\d+)$", re.IGNORECASE)
ISSUE_URL = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues/\d+$")
REQUIRED = {
    "advisory",
    "package",
    "version",
    "surface",
    "reason",
    "owner",
    "remediation_issue",
    "expires_on",
}


class NpmAuditError(RuntimeError):
    """The critical vulnerability policy was not satisfied."""


def _expiry(value, today):
    if not value:
        raise NpmAuditError("every npm audit exception requires expires_on")
    try:
        expires = dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise NpmAuditError(f"invalid npm exception expiry: {value!r}") from exc
    if expires < today:
        raise NpmAuditError(f"npm audit exception expired on {expires.isoformat()}")
    return expires


def _advisory_from_via(via):
    if not isinstance(via, dict) or via.get("severity") != "critical":
        return None
    candidates = [str(via.get("url", "")), str(via.get("name", ""))]
    for candidate in candidates:
        match = re.search(r"(?:GHSA-[0-9a-z-]+|CVE-\d{4}-\d+)", candidate, re.IGNORECASE)
        if match:
            return match.group(0).upper()
    raise NpmAuditError("critical npm advisory has no GHSA or CVE identifier")


def _installed_versions(lock_document, package):
    packages = lock_document.get("packages", {})
    if not isinstance(packages, dict):
        raise NpmAuditError("package lock has no packages object")
    suffix = f"node_modules/{package}"
    return {
        str(row.get("version"))
        for path, row in packages.items()
        if (path == suffix or path.endswith("/" + suffix)) and isinstance(row, dict)
    }


def evaluate_audit(audit_document, lock_document, allowlist_document, surface, today=None):
    today = today or dt.date.today()
    if allowlist_document.get("version") != 1:
        raise NpmAuditError("npm audit allowlist version must equal 1")
    exceptions = allowlist_document.get("exceptions")
    if not isinstance(exceptions, list):
        raise NpmAuditError("npm audit allowlist exceptions must be a list")
    allowed = set()
    for row in exceptions:
        if not isinstance(row, dict) or not REQUIRED.issubset(row):
            raise NpmAuditError("npm audit exception is missing mandatory fields")
        if not ADVISORY_ID.fullmatch(str(row["advisory"])):
            raise NpmAuditError("npm audit exception advisory must be a GHSA or CVE")
        if not ISSUE_URL.fullmatch(str(row["remediation_issue"])):
            raise NpmAuditError("npm audit exception requires a GitHub remediation issue")
        if not str(row["reason"]).strip() or not str(row["owner"]).strip():
            raise NpmAuditError("npm audit exception requires reason and owner")
        _expiry(row["expires_on"], today)
        allowed.add(
            (
                str(row["surface"]),
                str(row["package"]),
                str(row["version"]),
                str(row["advisory"]).upper(),
            )
        )

    findings = []
    vulnerabilities = audit_document.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        raise NpmAuditError("npm audit JSON has no vulnerabilities object")
    for package, vulnerability in vulnerabilities.items():
        if not isinstance(vulnerability, dict) or vulnerability.get("severity") != "critical":
            continue
        versions = _installed_versions(lock_document, package)
        if len(versions) != 1:
            raise NpmAuditError(
                f"critical package {package} must resolve to exactly one installed version"
            )
        version = next(iter(versions))
        advisories = {
            advisory
            for advisory in (
                _advisory_from_via(via) for via in vulnerability.get("via", [])
            )
            if advisory
        }
        if not advisories:
            referenced = {
                via for via in vulnerability.get("via", []) if isinstance(via, str)
            }
            if referenced and referenced.issubset(vulnerabilities):
                continue
            raise NpmAuditError(f"critical package {package} has no attributable advisory")
        for advisory in advisories:
            finding = (surface, package, version, advisory)
            findings.append(finding)
            if finding not in allowed:
                raise NpmAuditError(
                    f"unauthorized critical vulnerability: {surface}/{package}@{version} {advisory}"
                )
    return {
        "status": "PASS",
        "surface": surface,
        "critical_findings": len(findings),
        "authorized_findings": ["/".join(row) for row in sorted(findings)],
    }


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpmAuditError(f"invalid JSON file: {path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", required=True)
    parser.add_argument("--package-lock", required=True)
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--surface", required=True)
    args = parser.parse_args()
    try:
        result = evaluate_audit(
            _read_json(args.audit_json),
            _read_json(args.package_lock),
            _read_json(args.allowlist),
            args.surface,
        )
    except NpmAuditError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
