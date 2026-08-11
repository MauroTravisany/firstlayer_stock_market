"""Persistence facade for Strategy Brain WP-02.

The underlying implementation enforces that terminal experiment state is immutable
and that every experiment status update was not persisted exactly is treated as a
hard failure.
"""

from _experiment_registry_storage_core import (
    _ensure_experiment_identity_available,
    _experiment_for_run,
    _insert,
    _insert_experiment,
    _query,
    _resolve_parent_experiment,
    _set_run_status,
    _validate_snapshot,
    validate_snapshot_row,
)
from _experiment_registry_storage_candidates import (
    _activate_operational_candidates,
    _audit_candidate_rows,
    _link_operational_run,
    _mark_operational_run_failed,
    _table_ddl_extensions,
    rewrite_candidate_rows,
)
from _experiment_registry_storage_results import (
    _complete_audit_candidates,
    candidate_results_for_audit,
    candidate_rows_for_audit,
    link_audit_to_experiment,
)

__all__ = [name for name in globals() if not name.startswith("__")]
