"""Fail-closed policy for WP-03 join-key semantics.

GoogleSQL ``JOIN ... USING`` merges same-named columns into a composite input.
A later join may then see more than one matching field on its left side and
reject references as ambiguous. WP-03 therefore requires explicit, qualified
``ON`` predicates for every join.
"""

from __future__ import annotations

import re
from typing import Type

from tools import wp03_sql_policy as sql_policy


JOIN_KEY_POLICY_VERSION = "wp03-explicit-join-keys-v1"
_JOIN_USING = re.compile(r"\bUSING\s*\(", re.IGNORECASE)


class JoinKeyPolicyError(ValueError):
    """A compiled WP-03 query uses an unsafe implicit join-key merge."""


def using_join_findings(
    sql: str,
    *,
    error_cls: Type[Exception] = JoinKeyPolicyError,
    label: str = "compiled SQL",
) -> tuple[dict[str, int | str], ...]:
    """Return every executable ``USING (...)`` occurrence.

    Comments, quoted values and backtick identifiers are masked before the
    search, so documentation and literals cannot trigger a false positive.
    """

    masked = sql_policy.mask_google_sql_comments(
        sql,
        mask_literals=True,
        mask_identifiers=True,
        error_cls=error_cls,
        label=label,
    )
    findings = []
    for match in _JOIN_USING.finditer(masked):
        line = sql.count("\n", 0, match.start()) + 1
        previous_newline = sql.rfind("\n", 0, match.start())
        column = (
            match.start() + 1
            if previous_newline < 0
            else match.start() - previous_newline
        )
        findings.append(
            {
                "kind": "JOIN_USING",
                "line": line,
                "column": column,
            }
        )
    return tuple(findings)


def assert_explicit_join_predicates(
    sql: str,
    *,
    error_cls: Type[Exception] = JoinKeyPolicyError,
    label: str = "compiled SQL",
) -> None:
    """Require qualified ``ON`` predicates instead of merged USING keys."""

    findings = using_join_findings(sql, error_cls=error_cls, label=label)
    if not findings:
        return
    locations = ", ".join(
        f"{item['line']}:{item['column']}" for item in findings
    )
    raise error_cls(
        f"{label} uses JOIN USING at {locations}; WP-03 requires explicit "
        "qualified ON predicates"
    )
