"""Combine compatible valuation models into a calibrated, fail-closed decision."""

from __future__ import annotations

import math
import statistics
from typing import Iterable, Sequence

from .models import (
    Applicability,
    ModelDistribution,
    QualityAssessment,
    ValuationError,
    ValuationResult,
    ValuationState,
    result_payload_hash,
)
from .policy import ValuationPolicy
from .routing import EntityType, validate_model_route


_QUANTILE_KNOTS = (0.10, 0.25, 0.50, 0.75, 0.90)


def _inverse_piecewise(distribution: ModelDistribution, probability: float) -> float:
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
            fraction = (
                (probability - lower_probability)
                / (upper_probability - lower_probability)
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


def _mixture_samples(
    models: Sequence[ModelDistribution],
) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    grid = tuple((index + 0.5) / 40.0 for index in range(40))
    for model in models:
        effective_weight = model.weight * max(model.confidence, 0.05)
        point_weight = effective_weight / len(grid)
        samples.extend(
            (_inverse_piecewise(model, probability), point_weight)
            for probability in grid
        )
    return samples


def _probability(
    samples: Sequence[tuple[float, float]],
    predicate,
) -> float:
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
) -> float | None:
    rows = [
        (float(model.score), model.weight * max(model.confidence, 0.05))
        for model in models
        if model.score is not None and model.model_family.lower().startswith(prefix)
    ]
    return _weighted_mean(rows) if rows else None


def _intrinsic_score(models: Sequence[ModelDistribution]) -> float | None:
    rows = [
        (float(model.score), model.weight * max(model.confidence, 0.05))
        for model in models
        if model.score is not None
        and model.model_family.lower().startswith(
            ("fcff", "residual_income", "fcfe", "dividend_discount")
        )
    ]
    return _weighted_mean(rows) if rows else None


def _payload(
    *,
    current_price: float,
    fair_values: tuple[float, float, float, float, float],
    probability_economic: float,
    probability_expensive: float,
    relative_score: float | None,
    intrinsic_score: float | None,
    quality: QualityAssessment,
    agreement: float,
    confidence: float,
    state: ValuationState,
    entity_type: EntityType,
    policy: ValuationPolicy,
    models: Sequence[ModelDistribution],
    reasons: tuple[str, ...],
) -> dict:
    return {
        "current_price": current_price,
        "fair_value_p10": fair_values[0],
        "fair_value_p25": fair_values[1],
        "fair_value_p50": fair_values[2],
        "fair_value_p75": fair_values[3],
        "fair_value_p90": fair_values[4],
        "expected_return_p10": fair_values[0] / current_price - 1.0,
        "expected_return_p50": fair_values[2] / current_price - 1.0,
        "expected_return_p90": fair_values[4] / current_price - 1.0,
        "probability_economic": probability_economic,
        "probability_expensive": probability_expensive,
        "relative_valuation_score": relative_score,
        "intrinsic_valuation_score": intrinsic_score,
        "quality_score": quality.quality_score,
        "value_trap_probability": quality.value_trap_probability,
        "model_agreement_score": agreement,
        "valuation_confidence": confidence,
        "valuation_state": state,
        "quality_state": quality.quality_state,
        "risk_state": quality.risk_state,
        "entity_type": entity_type.value,
        "policy_version": policy.policy_version,
        "model_count": len(models),
        "model_hashes": tuple(sorted(model.model_hash for model in models)),
        "reason_codes": reasons,
        "production_change_allowed": False,
    }


def _build_result(payload: dict) -> ValuationResult:
    hash_payload = {
        key: value.value if hasattr(value, "value") else value
        for key, value in payload.items()
    }
    hash_payload["quality_state"] = payload["quality_state"].value
    hash_payload["risk_state"] = payload["risk_state"].value
    hash_payload["valuation_state"] = payload["valuation_state"].value
    payload = dict(payload)
    payload["result_hash"] = result_payload_hash(hash_payload)
    return ValuationResult(**payload)


def _insufficient_result(
    *,
    current_price: float,
    quality: QualityAssessment,
    policy: ValuationPolicy,
    models: Sequence[ModelDistribution],
    reasons: Iterable[str],
    entity_type: EntityType,
) -> ValuationResult:
    reason_codes = tuple(sorted(set(reasons) | set(quality.reason_codes)))
    payload = _payload(
        current_price=current_price,
        fair_values=(
            current_price,
            current_price,
            current_price,
            current_price,
            current_price,
        ),
        probability_economic=0.0,
        probability_expensive=0.0,
        relative_score=_score_for_family(models, "relative"),
        intrinsic_score=_intrinsic_score(models),
        quality=quality,
        agreement=0.0,
        confidence=0.0,
        state=ValuationState.DATOS_INSUFICIENTES,
        entity_type=entity_type,
        policy=policy,
        models=models,
        reasons=reason_codes,
    )
    return _build_result(payload)


def combine_valuation_models(
    *,
    current_price: float,
    estimates: Sequence[ModelDistribution],
    quality: QualityAssessment,
    policy: ValuationPolicy,
    entity_type: EntityType = EntityType.GENERAL_CORPORATE,
) -> ValuationResult:
    """Build an ensemble without allowing quality to redefine price.

    Model distributions must share the same snapshot, feature set, cutoff and
    currency. Quality and value-trap risk influence confidence/abstention only;
    they are not added to fair value or the relative/intrinsic scores.
    """

    if not math.isfinite(float(current_price)) or current_price <= 0:
        raise ValuationError("current_price must be positive")
    models = tuple(
        estimate
        for estimate in estimates
        if estimate.applicability is Applicability.APPLICABLE
    )
    if len(models) < policy.min_model_count:
        return _insufficient_result(
            current_price=current_price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=("INSUFFICIENT_APPLICABLE_MODELS",),
            entity_type=entity_type,
        )

    route = validate_model_route(entity_type, models)
    if route.status != "PASS":
        return _insufficient_result(
            current_price=current_price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=route.reason_codes,
            entity_type=entity_type,
        )

    compatibility_keys = {model.lineage.compatibility_key for model in models}
    if len(compatibility_keys) != 1:
        return _insufficient_result(
            current_price=current_price,
            quality=quality,
            policy=policy,
            models=models,
            reasons=("INCOMPATIBLE_MODEL_LINEAGE",),
            entity_type=entity_type,
        )

    samples = _mixture_samples(models)
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
            model.weight,
        )
        for model in models
    )
    confidence = (
        average_model_confidence
        * agreement
        * (0.5 + 0.5 * compactness)
        * (0.75 + 0.25 * quality.feature_coverage)
        * (1.0 - 0.35 * quality.value_trap_probability)
    )
    confidence = max(0.0, min(1.0, confidence))

    cheap_threshold = current_price * (1.0 + policy.cheap_upside_threshold)
    expensive_threshold = current_price / (
        1.0 + policy.expensive_downside_threshold
    )
    probability_economic = _probability(
        samples, lambda value: value >= cheap_threshold
    )
    probability_expensive = _probability(
        samples, lambda value: value <= expensive_threshold
    )

    reasons = set(quality.reason_codes)
    reasons.update(
        reason for model in models for reason in model.reason_codes
    )
    state = ValuationState.PRECIO_JUSTO
    if interval_width_ratio > policy.max_interval_width_ratio:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("FAIR_VALUE_INTERVAL_TOO_WIDE")
    elif quality.value_trap_probability >= policy.value_trap_abstain_threshold:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUE_TRAP_RISK_FORCES_ABSTENTION")
    elif confidence < policy.min_confidence:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUATION_CONFIDENCE_BELOW_POLICY")
    elif (
        probability_economic >= policy.probability_threshold
        and quality.value_trap_probability
        <= policy.max_value_trap_for_economic
    ):
        state = ValuationState.ECONOMICA
    elif probability_expensive >= policy.probability_threshold:
        state = ValuationState.CARA
    elif (
        probability_economic >= policy.probability_threshold
        and quality.value_trap_probability
        > policy.max_value_trap_for_economic
    ):
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("VALUE_TRAP_RISK_BLOCKS_ECONOMIC_CLASSIFICATION")
    elif abs(fair_values[2] / current_price - 1.0) <= policy.fair_value_band:
        state = ValuationState.PRECIO_JUSTO
        reasons.add("MEDIAN_INSIDE_POLICY_FAIR_VALUE_BAND")
    elif fair_values[1] <= current_price <= fair_values[3]:
        state = ValuationState.PRECIO_JUSTO
        reasons.add("PRICE_INSIDE_CENTRAL_FAIR_VALUE_INTERVAL")
    else:
        state = ValuationState.DATOS_INSUFICIENTES
        reasons.add("DIRECTIONAL_VALUATION_NOT_PROBABILISTICALLY_CONFIRMED")

    if (
        fair_values[1] <= current_price <= fair_values[3]
        and state is ValuationState.PRECIO_JUSTO
    ):
        reasons.add("PRICE_INSIDE_CENTRAL_FAIR_VALUE_INTERVAL")
    if agreement < 0.50:
        reasons.add("LOW_MODEL_AGREEMENT")

    payload = _payload(
        current_price=current_price,
        fair_values=fair_values,
        probability_economic=probability_economic,
        probability_expensive=probability_expensive,
        relative_score=_score_for_family(models, "relative"),
        intrinsic_score=_intrinsic_score(models),
        quality=quality,
        agreement=agreement,
        confidence=confidence,
        state=state,
        entity_type=entity_type,
        policy=policy,
        models=models,
        reasons=tuple(sorted(reasons)),
    )
    return _build_result(payload)
