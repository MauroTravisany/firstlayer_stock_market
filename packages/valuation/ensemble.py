"""Combine compatible valuation models into a calibrated, fail-closed decision."""

from __future__ import annotations

import math
import statistics
from typing import Iterable, Mapping, Sequence

from .calibration import (
    ModelCalibrationEvidence,
    RiskCalibrationEvidence,
    verify_model_calibration_registry,
    verify_risk_calibration_registry,
)
from .models import (
    Applicability,
    ModelDistribution,
    PriceObservation,
    QualityAssessment,
    RiskState,
    ValuationError,
    ValuationResult,
    ValuationState,
    valuation_result_payload_hash,
)
from .policy import ValuationPolicy
from .routing import EntityType, validate_model_route

_QUANTILE_KNOTS = (0.10, 0.25, 0.50, 0.75, 0.90)


def _inverse_piecewise(
    distribution: ModelDistribution,
    probability: float,
) -> float:
    """Interpolate the supplied quantiles with explicitly winsorized tails."""

    values = (
        distribution.p10,
        distribution.p25,
        distribution.p50,
        distribution.p75,
        distribution.p90,
    )
    if probability <= _QUANTILE_KNOTS[0]:
        return values[0]
    if probability >= _QUANTILE_KNOTS[-1]:
        return values[-1]
    for index in range(len(_QUANTILE_KNOTS) - 1):
        lower_probability = _QUANTILE_KNOTS[index]
        upper_probability = _QUANTILE_KNOTS[index + 1]
        if lower_probability <= probability <= upper_probability:
            fraction = (probability - lower_probability) / (
                upper_probability - lower_probability
            )
            return values[index] * (1 - fraction) + values[index + 1] * fraction
    raise ValuationError("unable to interpolate model distribution")


def _weighted_quantile(
    observations: Sequence[tuple[float, float]],
    probability: float,
) -> float:
    if not observations:
        raise ValuationError("weighted quantile sample is empty")
    ordered = sorted((float(value), float(weight)) for value, weight in observations)
    total = sum(weight for _, weight in ordered)
    if total <= 0 or not math.isfinite(total):
        raise ValuationError("weighted quantile sample has invalid weight")
    threshold = probability * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _effective_weight(
    model: ModelDistribution,
    policy: ValuationPolicy,
) -> float:
    # The policy, not the model payload, owns family weights. Structural
    # confidence only discounts a model after independent calibration passes.
    return policy.weight_for(model.model_family) * max(model.confidence, 0.05)


def _mixture_samples(
    models: Sequence[ModelDistribution],
    policy: ValuationPolicy,
) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    grid = tuple((index + 0.5) / 100.0 for index in range(100))
    for model in models:
        effective_weight = _effective_weight(model, policy)
        point_weight = effective_weight / len(grid)
        samples.extend(
            (_inverse_piecewise(model, probability), point_weight)
            for probability in grid
        )
    return samples


def _probability(samples: Sequence[tuple[float, float]], predicate) -> float:
    total = sum(weight for _, weight in samples)
    selected = sum(weight for value, weight in samples if predicate(value))
    return selected / total if total else 0.0


def _weighted_mean(values: Iterable[tuple[float, float]]) -> float:
    rows = list(values)
    total = sum(weight for _, weight in rows)
    if total <= 0:
        raise ValuationError("weighted mean requires positive total weight")
    return sum(value * weight for value, weight in rows) / total


def _score_for_family(
    models: Sequence[ModelDistribution],
    prefix: str,
    policy: ValuationPolicy,
) -> float | None:
    rows = [
        (float(model.score), _effective_weight(model, policy))
        for model in models
        if model.score is not None
        and model.model_family.lower().startswith(prefix)
    ]
    return _weighted_mean(rows) if rows else None


def _intrinsic_score(
    models: Sequence[ModelDistribution], policy: ValuationPolicy
) -> float | None:
    rows = [
        (float(model.score), _effective_weight(model, policy))
        for model in models
        if model.score is not None
        and model.model_family.lower().startswith(
            ("fcff", "residual_income", "fcfe", "dividend_discount")
        )
    ]
    return _weighted_mean(rows) if rows else None


def _base_payload(
    *,
    price: PriceObservation,
    valuation_as_of,
    quality: QualityAssessment,
    state: ValuationState,
    entity_type: EntityType,
    policy: ValuationPolicy,
    models: Sequence[ModelDistribution],
    reasons: tuple[str, ...],
) -> dict:
    return {
        "current_price": price.price,
        "price_observation_hash": price.observation_hash,
        "data_snapshot_id": price.data_snapshot_id,
        "currency": price.currency,
        "valuation_as_of": valuation_as_of,
        "quality_score": quality.quality_score,
        "value_trap_probability": quality.value_trap_probability,
        "valuation_state": state,
        "quality_state": quality.quality_state,
        "risk_state": quality.risk_state,
        "entity_type": entity_type.value,
        "policy_version": policy.policy_version,
        "policy_hash": policy.policy_hash,
        "quality_assessment_hash": quality.assessment_hash,
        "model_count": len(models),
        "model_hashes": tuple(sorted(model.model_hash for model in models)),
        "reason_codes": reasons,
        "production_change_allowed": False,
    }


def _build_result(payload: dict) -> ValuationResult:
    payload = dict(payload)
    payload["result_hash"] = valuation_result_payload_hash(payload)
    return ValuationResult(**payload)


def _insufficient_result(
    *,
    price: PriceObservation,
    quality: QualityAssessment,
    policy: ValuationPolicy,
    models: Sequence[ModelDistribution],
    reasons: Iterable[str],
    entity_type: EntityType,
    valuation_as_of,
) -> ValuationResult:
    reason_codes = tuple(sorted(set(reasons) | set(quality.reason_codes)))
    payload = _base_payload(
        price=price,
        valuation_as_of=valuation_as_of,
        quality=quality,
        state=ValuationState.DATOS_INSUFICIENTES,
        entity_type=entity_type,
        policy=policy,
        models=models,
        reasons=reason_codes,
    )
    payload.update(
        {
            "distribution_available": False,
            "fair_value_p10": None,
            "fair_value_p25": None,
            "fair_value_p50": None,
            "fair_value_p75": None,
            "fair_value_p90": None,
            "expected_return_p10": None,
            "expected_return_p50": None,
            "expected_return_p90": None,
            "probability_economic": None,
            "probability_expensive": None,
            "relative_valuation_score": _score_for_family(
                models, "relative", policy
            ),
            "intrinsic_valuation_score": _intrinsic_score(models, policy),
            "model_agreement_score": 0.0,
            "valuation_confidence": 0.0,
        }
    )
    return _build_result(payload)


def _verify_unique_models(models: Sequence[ModelDistribution]) -> tuple[str, ...]:
    reasons: list[str] = []
    names = [model.model_name.lower() for model in models]
    if len(set(names)) != len(names):
        reasons.append("DUPLICATE_MODEL_NAME")
    specs = [model.model_spec_hash for model in models]
    if len(set(specs)) != len(specs):
        reasons.append("DUPLICATE_MODEL_SPEC")
    families = [model.model_family.lower() for model in models]
    if len(set(families)) != len(families):
        reasons.append("DUPLICATE_MODEL_FAMILY")
    return tuple(reasons)


def combine_valuation_models(
    *,
    price: PriceObservation,
    estimates: Sequence[ModelDistribution],
    quality: QualityAssessment,
    policy: ValuationPolicy,
    entity_type: EntityType = EntityType.GENERAL_CORPORATE,
    model_calibration_registry: Mapping[
        str, ModelCalibrationEvidence
    ] | None = None,
    risk_calibration_registry: Mapping[
        str, RiskCalibrationEvidence
    ] | None = None,
) -> ValuationResult:
    """Build an ensemble without allowing quality to redefine price.

    Policy owns model weights. Model calibration evidence is verified against
    each model specification and a common OOS split. Quality and value-trap risk
    influence confidence and abstention only; they are never added to fair value.
    """

    if not isinstance(price, PriceObservation):
        raise ValuationError("price must be a PriceObservation")
    models = tuple(
        estimate
        for estimate in estimates
        if estimate.applicability is Applicability.APPLICABLE
    )
    valuation_as_of = (
        max(
            [quality.lineage.source_cutoff_at]
            + [model.lineage.source_cutoff_at for model in models]
        )
        if models
        else quality.lineage.source_cutoff_at
    )

    if len(models) < policy.min_model_count:
        return _insufficient_result(
            price=price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=("INSUFFICIENT_APPLICABLE_MODELS",),
            entity_type=entity_type,
            valuation_as_of=valuation_as_of,
        )
    duplicate_reasons = _verify_unique_models(models)
    if duplicate_reasons:
        return _insufficient_result(
            price=price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=duplicate_reasons,
            entity_type=entity_type,
            valuation_as_of=valuation_as_of,
        )

    route = validate_model_route(entity_type, models)
    if route.status != "PASS":
        return _insufficient_result(
            price=price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=route.reason_codes,
            entity_type=entity_type,
            valuation_as_of=valuation_as_of,
        )

    compatibility_keys = {model.lineage.compatibility_key for model in models}
    compatibility_keys.add(quality.lineage.compatibility_key)
    if len(compatibility_keys) != 1:
        return _insufficient_result(
            price=price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=("INCOMPATIBLE_MODEL_OR_QUALITY_LINEAGE",),
            entity_type=entity_type,
            valuation_as_of=valuation_as_of,
        )
    try:
        for model in models:
            model.lineage.assert_price_compatible(price)
        quality.lineage.assert_price_compatible(price)
    except ValuationError:
        return _insufficient_result(
            price=price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=("INCOMPATIBLE_PRICE_LINEAGE",),
            entity_type=entity_type,
            valuation_as_of=valuation_as_of,
        )

    if policy.require_calibrated_models:
        if model_calibration_registry is None:
            return _insufficient_result(
                price=price,
                quality=quality,
                policy=policy,
                models=models,
                reasons=("MODEL_CALIBRATION_REGISTRY_REQUIRED",),
                entity_type=entity_type,
                valuation_as_of=valuation_as_of,
            )
        try:
            verify_model_calibration_registry(models, model_calibration_registry)
        except ValuationError:
            return _insufficient_result(
                price=price,
                quality=quality,
                policy=policy,
                models=models,
                reasons=("MODEL_CALIBRATION_EVIDENCE_INVALID",),
                entity_type=entity_type,
                valuation_as_of=valuation_as_of,
            )

    samples = _mixture_samples(models, policy)
    fair_values = tuple(
        _weighted_quantile(samples, probability)
        for probability in (0.10, 0.25, 0.50, 0.75, 0.90)
    )
    medians = [model.p50 for model in models]
    median_center = statistics.median(medians)
    median_mad = statistics.median(abs(value - median_center) for value in medians)
    relative_model_dispersion = median_mad / fair_values[2]
    agreement = 1.0 / (1.0 + 4.0 * relative_model_dispersion)

    interval_width_ratio = (fair_values[4] - fair_values[0]) / fair_values[2]
    compactness = max(
        0.0,
        1.0 - interval_width_ratio / policy.max_interval_width_ratio,
    )
    average_model_confidence = _weighted_mean(
        (
            model.confidence,
            policy.weight_for(model.model_family),
        )
        for model in models
    )
    # Unverified risk never improves confidence. A high heuristic warning may
    # still reduce it conservatively.
    risk_modifier = (
        1.0 - 0.35 * quality.value_trap_probability
        if quality.risk_calibration_status.value == "PASS"
        else min(0.85, 1.0 - 0.35 * quality.value_trap_probability)
    )
    confidence = (
        average_model_confidence
        * agreement
        * (0.5 + 0.5 * compactness)
        * (0.70 + 0.30 * quality.feature_coverage)
        * (0.70 + 0.30 * quality.risk_feature_coverage)
        * risk_modifier
    )
    confidence = max(0.0, min(1.0, confidence))

    cheap_threshold = price.price * (1.0 + policy.cheap_upside_threshold)
    expensive_threshold = price.price / (1.0 + policy.expensive_downside_threshold)
    probability_economic = _probability(
        samples, lambda value: value >= cheap_threshold
    )
    probability_expensive = _probability(
        samples, lambda value: value <= expensive_threshold
    )

    reasons = set(quality.reason_codes)
    reasons.add("ENSEMBLE_TAILS_WINSORIZED_AT_P10_P90")
    reasons.update(reason for model in models for reason in model.reason_codes)
    state = ValuationState.PRECIO_JUSTO
    risk_calibration_valid = not policy.require_calibrated_value_trap
    if policy.require_calibrated_value_trap:
        if risk_calibration_registry is not None:
            try:
                verify_risk_calibration_registry(quality, risk_calibration_registry)
                risk_calibration_valid = True
            except ValuationError:
                risk_calibration_valid = False

    if interval_width_ratio > policy.max_interval_width_ratio:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("FAIR_VALUE_INTERVAL_TOO_WIDE")
    elif quality.value_trap_probability >= policy.value_trap_abstain_threshold:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUE_TRAP_RISK_FORCES_ABSTENTION")
    elif confidence < policy.min_confidence:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUATION_CONFIDENCE_BELOW_POLICY")
    elif probability_economic >= policy.probability_threshold and (
        quality.risk_state is RiskState.DESCONOCIDO
        or quality.risk_feature_coverage < policy.min_risk_coverage_for_economic
    ):
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUE_TRAP_RISK_COVERAGE_BLOCKS_ECONOMIC_CLASSIFICATION")
        if policy.require_calibrated_value_trap and not risk_calibration_valid:
            reasons.add(
                "VALUE_TRAP_CALIBRATION_REQUIRED_FOR_ECONOMIC_CLASSIFICATION"
            )
    elif probability_economic >= policy.probability_threshold and not risk_calibration_valid:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUE_TRAP_CALIBRATION_REQUIRED_FOR_ECONOMIC_CLASSIFICATION")
    elif (
        probability_economic >= policy.probability_threshold
        and quality.value_trap_probability <= policy.max_value_trap_for_economic
    ):
        state = ValuationState.ECONOMICA
    elif probability_expensive >= policy.probability_threshold:
        state = ValuationState.CARA
    elif (
        probability_economic >= policy.probability_threshold
        and quality.value_trap_probability > policy.max_value_trap_for_economic
    ):
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUE_TRAP_RISK_BLOCKS_ECONOMIC_CLASSIFICATION")
    elif abs(fair_values[2] / price.price - 1.0) <= policy.fair_value_band:
        state = ValuationState.PRECIO_JUSTO
        reasons.add("MEDIAN_INSIDE_POLICY_FAIR_VALUE_BAND")
    elif fair_values[1] <= price.price <= fair_values[3]:
        state = ValuationState.PRECIO_JUSTO
        reasons.add("PRICE_INSIDE_CENTRAL_FAIR_VALUE_INTERVAL")
    else:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("DIRECTIONAL_VALUATION_NOT_PROBABILISTICALLY_CONFIRMED")

    if fair_values[1] <= price.price <= fair_values[3] and state is ValuationState.PRECIO_JUSTO:
        reasons.add("PRICE_INSIDE_CENTRAL_FAIR_VALUE_INTERVAL")
    if agreement < 0.50:
        reasons.add("LOW_MODEL_AGREEMENT")

    payload = _base_payload(
        price=price,
        valuation_as_of=valuation_as_of,
        quality=quality,
        state=state,
        entity_type=entity_type,
        policy=policy,
        models=models,
        reasons=tuple(sorted(reasons)),
    )
    payload.update(
        {
            "distribution_available": True,
            "fair_value_p10": fair_values[0],
            "fair_value_p25": fair_values[1],
            "fair_value_p50": fair_values[2],
            "fair_value_p75": fair_values[3],
            "fair_value_p90": fair_values[4],
            "expected_return_p10": fair_values[0] / price.price - 1.0,
            "expected_return_p50": fair_values[2] / price.price - 1.0,
            "expected_return_p90": fair_values[4] / price.price - 1.0,
            "probability_economic": probability_economic,
            "probability_expensive": probability_expensive,
            "relative_valuation_score": _score_for_family(
                models, "relative", policy
            ),
            "intrinsic_valuation_score": _intrinsic_score(models, policy),
            "model_agreement_score": agreement,
            "valuation_confidence": confidence,
        }
    )
    return _build_result(payload)
