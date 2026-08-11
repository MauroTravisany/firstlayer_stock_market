"""Install WP-02 experiment lineage around the legacy Strategy Brain."""

from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from experiment_identity import (
    _CURRENT,
    _require_payload,
    CANDIDATE_ID,
    HEX64,
    RUN_ID,
    UUID_CANONICAL,
    RegistryAdapterError,
    build_candidate_id,
    build_run_id,
    candidate_configuration,
    canonical_json,
    create_context,
    dependency_lock_hash,
    load_contract_manifest,
    new_experiment_id,
    sha256_value,
)
from experiment_registry_storage import (
    _audit_candidate_rows,
    _complete_audit_candidates,
    _ensure_experiment_identity_available,
    _experiment_for_run,
    _insert,
    _insert_experiment,
    _link_operational_run,
    _resolve_parent_experiment,
    _set_run_status,
    _table_ddl_extensions,
    _validate_snapshot,
    candidate_results_for_audit,
    candidate_rows_for_audit,
    link_audit_to_experiment,
    rewrite_candidate_rows,
    validate_snapshot_row,
)

def install(legacy):
    if getattr(legacy, "_WP02_REGISTRY_INSTALLED", False):
        return legacy

    original_table_ddl = legacy._table_ddl
    original_candidate_rows = legacy._candidate_rows
    original_iterative_rows = legacy._iterative_candidate_rows
    original_parent_candidates = legacy._parent_candidates
    original_generate = legacy._generate
    original_review = legacy._review

    def table_ddl(config):
        return [*original_table_ddl(config), *_table_ddl_extensions(config)]

    def candidate_rows(*args, **kwargs):
        records = original_candidate_rows(*args, **kwargs)
        context = _CURRENT.get()
        if context is None:
            raise RegistryAdapterError("candidate generation lacks experiment context")
        return rewrite_candidate_rows(records, context)

    def iterative_rows(*args, **kwargs):
        records = original_iterative_rows(*args, **kwargs)
        context = _CURRENT.get()
        if context is None:
            raise RegistryAdapterError("candidate generation lacks experiment context")
        return rewrite_candidate_rows(records, context)

    def parent_candidates(
        client, config, asset_scope, target_strategy_version, parent_run_id=None
    ):
        context = _CURRENT.get()
        if context is None:
            return original_parent_candidates(
                client,
                config,
                asset_scope,
                target_strategy_version,
                parent_run_id,
            )
        explicit_parent = context["parent_run_id"]
        if explicit_parent is None:
            return []
        if parent_run_id not in (None, explicit_parent):
            raise RegistryAdapterError("legacy parent selection differs from registry lineage")
        rows = original_parent_candidates(
            client,
            config,
            asset_scope,
            target_strategy_version,
            explicit_parent,
        )
        if not rows:
            raise RegistryAdapterError(
                "explicit parent run has no eligible audited candidate"
            )
        return rows

    def generate(client, config, payload):
        payload = dict(payload)
        context = create_context(payload, config, legacy)
        token = _CURRENT.set(context)
        inserted = False
        try:
            _validate_snapshot(client, config, legacy, context)
            _resolve_parent_experiment(client, config, legacy, context)
            _ensure_experiment_identity_available(client, config, legacy, context)
            _insert_experiment(client, config, context)
            inserted = True
            result = original_generate(client, config, payload)
            if result.get("status") == "CONVERGED":
                _set_run_status(
                    client, config, legacy, context, "CANCELLED", completed=True
                )
                return {**result, "experiment_id": context["experiment_id"]}
            if result.get("parent_run_id") != context["parent_run_id"]:
                raise RegistryAdapterError("generated run parent differs from registry lineage")
            candidates = candidate_rows_for_audit(
                client, config, legacy, context["run_id"]
            )
            audit_rows = _audit_candidate_rows(context, candidates)
            if not audit_rows:
                raise RegistryAdapterError("experiment generated no candidates")
            _insert(
                client,
                config["audit_candidates_table"],
                audit_rows,
                row_ids=[
                    f"{row['experiment_id']}:{row['run_id']}:{row['candidate_id']}"
                    for row in audit_rows
                ],
            )
            context["hypothesis_count"] = len(audit_rows)
            _link_operational_run(client, config, legacy, context)
            _set_run_status(
                client,
                config,
                legacy,
                context,
                "CANDIDATES_READY",
                hypothesis_count=len(audit_rows),
            )
            return {
                **result,
                "experiment_id": context["experiment_id"],
                "configuration_hash": context["configuration_hash"],
                "dependency_lock_hash": context["dependency_lock_hash"],
                "contract_set_hash": context["contract_set_hash"],
                "data_snapshot_id": context["data_snapshot_id"],
                "data_snapshot_checksum": context["data_snapshot_checksum"],
            }
        except Exception:
            if inserted:
                try:
                    current = _experiment_for_run(
                        client, config, legacy, context["run_id"]
                    )
                    if current and current["status"] not in {
                        "COMPLETED",
                        "REJECTED",
                        "FAILED",
                        "CANCELLED",
                    }:
                        _set_run_status(
                            client, config, legacy, context, "FAILED", completed=True
                        )
                except Exception:
                    pass
            raise
        finally:
            _CURRENT.reset(token)

    def review(client, config, payload):
        payload = dict(payload)
        run_id = _require_payload(payload, "run_id").lower()
        if not RUN_ID.fullmatch(run_id):
            raise RegistryAdapterError("review run_id must use run_<sha256>")
        context = _experiment_for_run(client, config, legacy, run_id)
        if not context:
            raise RegistryAdapterError(f"no audit experiment exists for run {run_id}")
        if context["status"] != "CANDIDATES_READY":
            raise RegistryAdapterError(
                f"experiment is not reviewable from status {context['status']}"
            )
        _set_run_status(client, config, legacy, context, "RUNNING")
        try:
            result = original_review(client, config, payload)
            candidates = candidate_rows_for_audit(client, config, legacy, run_id)
            candidate_results = candidate_results_for_audit(
                client, config, legacy, run_id
            )
            completed_candidates = _complete_audit_candidates(
                client,
                config,
                legacy,
                context,
                candidates,
                candidate_results,
            )
            results_manifest = {
                "experiment_id": context["experiment_id"],
                "run_id": run_id,
                "data_snapshot_id": context.get("data_snapshot_id"),
                "review": result,
                "candidate_results": completed_candidates,
            }
            content_json = canonical_json(results_manifest)
            checksum = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
            artifact_id = "artifact_" + sha256_value(
                {
                    "experiment_id": context["experiment_id"],
                    "run_id": run_id,
                    "artifact_type": "RESULT_SUMMARY",
                    "checksum": checksum,
                }
            )
            decision_evidence = {
                "generation_outcome": result.get("generation_outcome"),
                "promotion_recommendation": result.get("promotion_recommendation"),
                "selected_candidates": result.get("selected_candidates"),
                "result_checksum": checksum,
            }
            decision_id = "decision_" + sha256_value(
                {
                    "experiment_id": context["experiment_id"],
                    "run_id": run_id,
                    "decision_type": "MECHANICAL_REVIEW",
                    "evidence": decision_evidence,
                }
            )
            created_at = dt.datetime.now(dt.timezone.utc).isoformat()
            _insert(
                client,
                config["audit_artifacts_table"],
                [
                    {
                        "experiment_id": context["experiment_id"],
                        "run_id": run_id,
                        "artifact_id": artifact_id,
                        "candidate_id": None,
                        "artifact_type": "RESULT_SUMMARY",
                        "uri": f"inline://audit_experiment_artifacts/{artifact_id}",
                        "media_type": "application/json",
                        "content_json": content_json,
                        "checksum": checksum,
                        "size_bytes": len(content_json.encode("utf-8")),
                        "immutable": True,
                        "created_at": created_at,
                    }
                ],
                row_ids=[artifact_id],
            )
            _insert(
                client,
                config["audit_decisions_table"],
                [
                    {
                        "experiment_id": context["experiment_id"],
                        "run_id": run_id,
                        "decision_id": decision_id,
                        "candidate_id": None,
                        "decision_type": "MECHANICAL_REVIEW",
                        "decision_status": "RECORDED",
                        "reason_code": str(
                            result.get("generation_outcome") or "REVIEW_RECORDED"
                        ),
                        "evidence_json": canonical_json(decision_evidence),
                        "actor_type": "SYSTEM",
                        "actor_id": "strategy_brain",
                        "production_change_allowed": False,
                        "created_at": created_at,
                    }
                ],
                row_ids=[decision_id],
            )
            _set_run_status(
                client,
                config,
                legacy,
                context,
                "COMPLETED",
                results_checksum=checksum,
                completed=True,
            )
            link_audit_to_experiment(client, config, legacy, context, run_id)
            return {
                **result,
                "experiment_id": context["experiment_id"],
                "results_checksum": checksum,
            }
        except Exception:
            try:
                current = _experiment_for_run(client, config, legacy, run_id)
                if current and current["status"] == "RUNNING":
                    _set_run_status(
                        client, config, legacy, context, "FAILED", completed=True
                    )
            except Exception:
                pass
            raise

    legacy._table_ddl = table_ddl
    legacy._candidate_rows = candidate_rows
    legacy._iterative_candidate_rows = iterative_rows
    legacy._parent_candidates = parent_candidates
    legacy._generate = generate
    legacy._review = review
    legacy._WP02_REGISTRY_INSTALLED = True
    return legacy
