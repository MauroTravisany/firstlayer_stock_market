"""Stable WP-03 compiled SQL schema-check entrypoint.

The implementation lives in :mod:`tools.wp03_compiled_sql_semantic_preflight`.
This module is the public handoff path used by operators and Codex. Keeping the
entrypoint stable prevents runbooks from depending on an internal module name.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools import wp03_compiled_sql_semantic_preflight as _implementation


# Explicitly re-export the supported API so tests, operators and future callers
# do not need to import the internal implementation module.
ACKNOWLEDGEMENT = _implementation.ACKNOWLEDGEMENT
REQUIRED_OUTPUTS = _implementation.REQUIRED_OUTPUTS
RAW_OUTPUT = _implementation.RAW_OUTPUT
ALLOWED_OPERATIONAL_INPUTS = _implementation.ALLOWED_OPERATIONAL_INPUTS
SemanticPreflightError = _implementation.SemanticPreflightError
Target = _implementation.Target
CompiledAction = _implementation.CompiledAction
verify_clean_checkout = _implementation.verify_clean_checkout
validate_scope = _implementation.validate_scope
load_actions_document = _implementation.load_actions_document
parse_action = _implementation.parse_action
build_plan = _implementation.build_plan
verify_plan_checksum = _implementation.verify_plan_checksum
execute_schema_graph = _implementation.execute_schema_graph
main = _implementation.main


def __getattr__(name: str) -> Any:
    """Delegate non-private compatibility attributes to the implementation."""

    if name.startswith("_"):
        raise AttributeError(name)
    try:
        return getattr(_implementation, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | {
            name
            for name in dir(_implementation)
            if not name.startswith("_")
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
