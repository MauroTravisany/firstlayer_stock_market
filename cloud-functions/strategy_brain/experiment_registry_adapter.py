"""Install WP-02 experiment lineage around the legacy Strategy Brain."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging

from experiment_identity import (
    _CURRENT,
    _require_payload,
    RUN_ID,
    RegistryAdapterError,
    build_artifact_id,
    build_decision_id,
    canonical_json,
    create_context,
)

logger = logging.getLogger(__name__)

from experiment_registry_storage import (
    _activate_operational_candidates,
    _audit_candidate_rows,
    _complete_audit_candidates,
    _ensure_experiment_identity_available,
    _experiment_for_run,
    _insert,
    _insert_experiment,
    _link_operational_run,
    _mark_operational_run_failed,
    _resolve_parent_experiment,
    _set_run_status,
    _table_ddl_extensions,
    _validate_snapshot,
    candidate_results_for_audit,
    candidate_rows_for_audit,
    link_audit_to_experiment,
    rewrite_candidate_rows,
)


def _baseline_reference(candidate_scores):
    baselines = [
        row
        for row in candidate_scores
        if str(row.get("candidate_label") or "").strip() == "Control sin cambio"
    ]
    if len(baselines) != 1:
        raise RegistryAdapterError(
            "initial experiment must expose exactly one labeled baseline candidate"
        )
    return baselines[0]


def install(legacy):
    if getattr(legacy, "_WP02_REGISTRY_INSTALLED", False):
        return legacy

    original_table_ddl = legacy._table_ddl
    original_candidate_rows = legacy._candidate_rows
    original_iterative_rows = legacy._iterative_candidate_rows
    original_parent_candidates = legacy._parent_candidates
    original_generate = legacy._generate
    original_review = legacy._review
    original_previous_best_score = legacy._previous_best_score

    def table_ddl(config):
        return [*original_table_ddl(config), *_table_ddl_extensions(config)]

    def candidate_rows(*args, **kwargs):
        context = _CURRENT.get()
        if context is None:
            raise RegistryAdapterError(
                "candidate generation lacks experiment context"
            )
        return rewrite_candidate_rows(
            original_candidate_rows(*args, **kwargs), context
        )

    def iterative_rows(*args, **kwargs):
        context = _CURRENT.get()
        if context is None:
            raise RegistryAdapterError(
                "candidate generation lacks experiment context"
            )
        return rewrite_candidate_rows(
            original_iterative_rows(*args, **kwargs), context
        )

    def parent_candidates(
        client,
        config,
        asset_scope,
        target_strategy_version,
        parent_run_id=None,
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
            raise RegistryAdapterError(
                "legacy parent selection differs from registry lineage"
            )
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

    def previous_best_score(
        client, config, run_id, asset_scope, target_strategy_version
    ):
        result = original_previous_best_score(
            client, config, run_id, asset_scope, target_strategy_version
        )
        if result is not None:
            return result
        return _baseline_reference(
            legacy._validation_candidate_scores(client, config, run_id)
        )

    def generate(client, config, payload):
        payload = dict(payload)
        context = create_context(payload, config, legacy)
        token = _CURRENT.set(context)
        inserted = False
        try:
            _validate_snapshot(client, config, legacy, context)
            _resolve_parent_experiment(client, config, legacy, context)
            _ensure_experiment_identity_available(
                client, config, legacy, context
            )
            _insert_experiment(client, config, context)
            inserted = True

            result = original_generate(client, config, payload)
            if result.get("status") == "CONVERGED":
                _set_run_status(
                    client,
                    config,
                    legacy,
                    context,
                    "CANCELLED",
                    completed=True,
                )
                return {**result, "experiment_id": context["experiment_id"]}
            if result.get("run_id") != context["run_id"]:
                raise RegistryAdapterError(
                    "generated run differs from allocated audit run_id"
                )
            if result.get("parent_run_id") != context["parent_run_id"]:
                raise RegistryAdapterError(
                    "generated run parent differs from registry lineage"
                )

            candidates = candidate_rows_for_audit(
                client, config, legacy, context["run_id"]
            )
            if not candidates or any(
                row.get("candidate_status") != "REGISTRY_PENDING"
                for row in candidates
            ):
                raise RegistryAdapterError(
                    "operational candidates escaped the registry-pending gate"
                )
            audit_rows = _audit_candidate_rows(context, candidates)
            if len(audit_rows) != len(candidates):
                raise RegistryAdapterError("audit candidate set is incomplete")
            if len(audit_rows) > context["hypothesis_count"]:
                raise RegistryAdapterError(
                    "candidate set exceeds the declared hypothesis budget"
                )
            context["hypothesis_count"] = len(audit_rows)
            _insert(
                client,
                config["audit_candidates_table"],
                audit_rows,
                row_ids=[
                    f"{row['experiment_id']}:{row['run_id']}:{row['candidate_id']}"
                    for row in audit_rows
                ],
            )
            _link_operational_run(client, config, legacy, context)
            _activate_operational_candidates(
                client, config, legacy, context, len(audit_rows)
            )
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
                "schema_snapshot_hash": context["schema_snapshot_hash"],
                "data_snapshot_id": context["data_snapshot_id"],
                "data_snapshot_checksum": context["data_snapshot_checksum"],
                "production_change_allowed": False,
            }
        except Exception as exc:
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
                            client,
                            config,
                            legacy,
                            context,
                            "FAILED",
                            failure_reason=(
                                f"generation failed: {type(exc).__name__}"
                            ),
                            completed=True,
                        )
                    _mark_operational_run_failed(
                        client, config, legacy, context
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist generation rollback evidence for run %s",
                        context.get("run_id"),
                    )
            raise
        finally:
            _CURRENT.reset(token)

    def review(client, config, payload):
        payload = dict(payload)
        run_id = _require_payload(payload, "run_id").lower()
        if not RUN_ID.fullmatch(run_id):
            raise RegistryAdapterError(
                "review run_id must use run_<sha256>"
            )
        context = _experiment_for_run(client, config, legacy, run_id)
        if not context:
            raise RegistryAdapterError(
                f"no audit experiment exists for run {run_id}"
            )
        if context["status"] != "CANDIDATES_READY":
            raise RegistryAdapterError(
                f"experiment is not reviewable from status {context['status']}"
            )
        _set_run_status(client, config, legacy, context, "RUNNING")
        try:
            result = original_review(client, config, payload)
            candidates = candidate_rows_for_audit(
                client, config, legacy, run_id
            )
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
            checksum = hashlib.sha256(
                content_json.encode("utf-8")
            ).hexdigest()
            artifact_id = build_artifact_id(
                context["experiment_id"],
                run_id,
                "RESULT_SUMMARY",
                checksum,
                None,
            )
            generation_outcome = str(
                result.get("generation_outcome") or "REVIEW_RECORDED"
            )
            decision_evidence = {
                "generation_outcome": generation_outcome,
                "promotion_recommendation": result.get(
                    "promotion_recommendation"
                ),
                "result_checksum": checksum,
            }
            decision_id = build_decision_id(
                context["experiment_id"],
                run_id,
                "MECHANICAL_REVIEW",
                decision_evidence,
                None,
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
                        "uri": (
                            "inline://audit_experiment_artifacts/"
                            f"{artifact_id}"
                        ),
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
                        "reason_code": generation_outcome,
                        "evidence_json": canonical_json(decision_evidence),
                        "actor_type": "SYSTEM",
                        "actor_id": "strategy_brain",
                        "production_change_allowed": False,
                        "created_at": created_at,
                    }
                ],
                row_ids=[decision_id],
            )
            link_audit_to_experiment(
                client, config, legacy, context, run_id
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
            return {
                **result,
                "experiment_id": context["experiment_id"],
                "results_checksum": checksum,
                "production_change_allowed": False,
            }
        except Exception as exc:
            try:
                current = _experiment_for_run(client, config, legacy, run_id)
                if current and current["status"] == "RUNNING":
                    _set_run_status(
                        client,
                        config,
                        legacy,
                        context,
                        "FAILED",
                        failure_reason=f"review failed: {type(exc).__name__}",
                        completed=True,
                    )
            except Exception:
                logger.exception(
                    "Failed to persist review failure state for run %s",
                    run_id,
                )
            raise

    legacy._table_ddl = table_ddl
    legacy._candidate_rows = candidate_rows
    legacy._iterative_candidate_rows = iterative_rows
    legacy._parent_candidates = parent_candidates
    legacy._previous_best_score = previous_best_score
    legacy._generate = generate
    legacy._review = review
    legacy._WP02_REGISTRY_INSTALLED = True
    return legacy
