"""Peer-conditioned relative valuation with robust scaling and ridge residuals."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .models import (
    Applicability,
    ModelDistribution,
    ValuationError,
    ValuationLineage,
)
from .policy import ValuationPolicy


class RelativeMetric(str, Enum):
    PE = "PE"
    PS = "PS"
    PB = "PB"
    P_FCF = "P_FCF"
    EV_EBITDA = "EV_EBITDA"


@dataclass(frozen=True)
class PeerObservation:
    ticker: str
    observed_multiple: float
    features: Mapping[str, float]

    def __post_init__(self) -> None:
        if not str(self.ticker).strip():
            raise ValuationError("peer ticker is required")
        multiple = float(self.observed_multiple)
        if not math.isfinite(multiple) or multiple <= 0:
            raise ValuationError("peer observed_multiple must be positive")
        if not self.features:
            raise ValuationError("peer features cannot be empty")
        for name, value in self.features.items():
            if not str(name).strip():
                raise ValuationError("feature name cannot be empty")
            if not math.isfinite(float(value)):
                raise ValuationError(f"feature {name} must be finite")


@dataclass(frozen=True)
class RelativeSubject:
    ticker: str
    metric: RelativeMetric
    current_price: float
    features: Mapping[str, float]
    anchor_per_share: float | None = None
    enterprise_anchor: float | None = None
    net_debt: float = 0.0
    shares_outstanding: float | None = None

    def __post_init__(self) -> None:
        if not str(self.ticker).strip():
            raise ValuationError("subject ticker is required")
        if not math.isfinite(float(self.current_price)) or self.current_price <= 0:
            raise ValuationError("current_price must be positive")
        if not self.features:
            raise ValuationError("subject features cannot be empty")
        for name, value in self.features.items():
            if not math.isfinite(float(value)):
                raise ValuationError(f"feature {name} must be finite")
        if self.metric is RelativeMetric.EV_EBITDA:
            if (
                self.enterprise_anchor is None
                or not math.isfinite(float(self.enterprise_anchor))
                or self.enterprise_anchor <= 0
            ):
                raise ValuationError("EV_EBITDA requires positive enterprise_anchor")
            if (
                self.shares_outstanding is None
                or not math.isfinite(float(self.shares_outstanding))
                or self.shares_outstanding <= 0
            ):
                raise ValuationError("EV_EBITDA requires positive shares_outstanding")
            if not math.isfinite(float(self.net_debt)):
                raise ValuationError("net_debt must be finite")
        else:
            if (
                self.anchor_per_share is None
                or not math.isfinite(float(self.anchor_per_share))
                or self.anchor_per_share <= 0
            ):
                raise ValuationError(
                    f"{self.metric.value} requires positive anchor_per_share"
                )


@dataclass(frozen=True)
class RelativeValuationEstimate:
    distribution: ModelDistribution
    observed_multiple: float
    predicted_multiple: float
    log_residual: float
    robust_residual_z: float
    peer_count: int
    feature_names: tuple[str, ...]
    residual_scale: float
    r_squared: float
    extrapolated_features: tuple[str, ...] = ()


def _median(values: Sequence[float]) -> float:
    if not values:
        raise ValuationError("at least one observation is required")
    return float(statistics.median(float(value) for value in values))


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValuationError("cannot compute a quantile from an empty sample")
    if not 0 <= probability <= 1:
        raise ValuationError("quantile probability must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _robust_center_scale(values: Sequence[float]) -> tuple[float, float]:
    center = _median(values)
    mad = _median([abs(float(value) - center) for value in values])
    scale = 1.4826 * mad
    if scale <= 1e-12:
        scale = statistics.pstdev(float(value) for value in values)
    if scale <= 1e-12:
        scale = 1.0
    return center, float(scale)


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    if len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValuationError("linear system dimensions are inconsistent")
    augmented = [
        [float(value) for value in matrix[row]] + [float(vector[row])]
        for row in range(size)
    ]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            raise ValuationError("relative valuation regression is singular")
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        augmented[column] = [value / pivot_value for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def _ridge_coefficients(
    design: Sequence[Sequence[float]],
    target: Sequence[float],
    penalty: float,
) -> list[float]:
    if not design or len(design) != len(target):
        raise ValuationError("regression design and target sizes must match")
    width = len(design[0])
    if width == 0 or any(len(row) != width for row in design):
        raise ValuationError("regression design rows must have equal width")
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for row, y_value in zip(design, target):
        for left in range(width):
            xty[left] += row[left] * y_value
            for right in range(width):
                xtx[left][right] += row[left] * row[right]
    for index in range(1, width):
        xtx[index][index] += penalty
    return _solve_linear_system(xtx, xty)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _observed_multiple(subject: RelativeSubject) -> float:
    if subject.metric is RelativeMetric.EV_EBITDA:
        enterprise_value = (
            subject.current_price * float(subject.shares_outstanding)
            + float(subject.net_debt)
        )
        multiple = enterprise_value / float(subject.enterprise_anchor)
    else:
        multiple = subject.current_price / float(subject.anchor_per_share)
    if not math.isfinite(multiple) or multiple <= 0:
        raise ValuationError("subject observed multiple must be positive")
    return multiple


def _implied_price(
    subject: RelativeSubject,
    predicted_multiple: float,
) -> float:
    if not math.isfinite(predicted_multiple) or predicted_multiple <= 0:
        raise ValuationError("predicted multiple must be positive")
    if subject.metric is RelativeMetric.EV_EBITDA:
        equity_value = (
            predicted_multiple * float(subject.enterprise_anchor)
            - float(subject.net_debt)
        )
        price = equity_value / float(subject.shares_outstanding)
    else:
        price = predicted_multiple * float(subject.anchor_per_share)
    if not math.isfinite(price) or price <= 0:
        raise ValuationError("relative valuation implies non-positive equity value")
    return price


def estimate_relative_value(
    subject: RelativeSubject,
    peers: Sequence[PeerObservation],
    lineage: ValuationLineage,
    policy: ValuationPolicy,
) -> RelativeValuationEstimate:
    """Estimate a fair-value distribution from peer multiples and fundamentals.

    ``log(multiple)`` is fitted on robustly standardized fundamentals using ridge
    regression. The empirical residual distribution supplies uncertainty. A
    high-quality subject may deserve a higher expected multiple through its
    *features*, but quality is never added directly to the final price label.
    """

    if len(peers) < policy.min_peer_count:
        raise ValuationError(
            f"relative valuation requires at least {policy.min_peer_count} peers"
        )
    feature_names = tuple(sorted(subject.features))
    if not feature_names:
        raise ValuationError("at least one relative valuation feature is required")
    for peer in peers:
        missing = sorted(set(feature_names) - set(peer.features))
        extra = sorted(set(peer.features) - set(feature_names))
        if missing or extra:
            raise ValuationError(
                f"peer {peer.ticker} feature mismatch; missing={missing}, extra={extra}"
            )

    centers: dict[str, float] = {}
    scales: dict[str, float] = {}
    for feature in feature_names:
        centers[feature], scales[feature] = _robust_center_scale(
            [float(peer.features[feature]) for peer in peers]
        )

    def encoded(features: Mapping[str, float]) -> list[float]:
        return [1.0] + [
            (float(features[name]) - centers[name]) / scales[name]
            for name in feature_names
        ]

    design = [encoded(peer.features) for peer in peers]
    target = [math.log(float(peer.observed_multiple)) for peer in peers]
    coefficients = _ridge_coefficients(design, target, policy.ridge_penalty)
    fitted = [_dot(row, coefficients) for row in design]
    residuals = [actual - prediction for actual, prediction in zip(target, fitted)]
    residual_center, residual_scale = _robust_center_scale(residuals)
    centered_residuals = [
        residual - residual_center for residual in residuals
    ]
    subject_vector = encoded(subject.features)
    predicted_log_multiple = (
        _dot(subject_vector, coefficients) + residual_center
    )
    predicted_multiple = math.exp(predicted_log_multiple)
    observed_multiple = _observed_multiple(subject)
    log_residual = math.log(observed_multiple) - predicted_log_multiple
    robust_residual_z = -log_residual / residual_scale

    quantile_probabilities = (0.10, 0.25, 0.50, 0.75, 0.90)
    residual_quantiles = [
        _quantile(centered_residuals, probability)
        for probability in quantile_probabilities
    ]
    fair_values = [
        _implied_price(subject, math.exp(predicted_log_multiple + residual))
        for residual in residual_quantiles
    ]

    target_mean = sum(target) / len(target)
    total_sum_squares = sum((value - target_mean) ** 2 for value in target)
    residual_sum_squares = sum(
        (actual - prediction) ** 2 for actual, prediction in zip(target, fitted)
    )
    r_squared = (
        1.0 - residual_sum_squares / total_sum_squares
        if total_sum_squares > 1e-12
        else 0.0
    )
    rmse = math.sqrt(residual_sum_squares / len(residuals))
    sample_factor = min(1.0, len(peers) / (2.0 * policy.min_peer_count))
    dispersion_factor = 1.0 / (1.0 + rmse)
    fit_factor = max(0.0, min(1.0, (r_squared + 1.0) / 2.0))
    confidence = max(
        0.0,
        min(1.0, sample_factor * dispersion_factor * (0.5 + 0.5 * fit_factor)),
    )

    extrapolated = tuple(
        name
        for name, encoded_value in zip(feature_names, subject_vector[1:])
        if abs(encoded_value) > 4.0
    )
    reasons = []
    if extrapolated:
        confidence *= 0.65
        reasons.append("SUBJECT_FEATURE_EXTRAPOLATION")
    if r_squared < 0:
        reasons.append("WEAK_RELATIVE_FIT")
    if residual_scale > 0.75:
        reasons.append("WIDE_PEER_MULTIPLE_DISPERSION")

    family = f"relative_{subject.metric.value.lower()}"
    distribution = ModelDistribution(
        model_name=f"{family}_ridge_v1",
        model_family=family,
        p10=fair_values[0],
        p25=fair_values[1],
        p50=fair_values[2],
        p75=fair_values[3],
        p90=fair_values[4],
        confidence=confidence,
        lineage=lineage,
        applicability=Applicability.APPLICABLE,
        weight=policy.weight_for("relative"),
        score=robust_residual_z,
        reason_codes=tuple(reasons),
        production_change_allowed=False,
    )
    return RelativeValuationEstimate(
        distribution=distribution,
        observed_multiple=observed_multiple,
        predicted_multiple=predicted_multiple,
        log_residual=log_residual,
        robust_residual_z=robust_residual_z,
        peer_count=len(peers),
        feature_names=feature_names,
        residual_scale=residual_scale,
        r_squared=r_squared,
        extrapolated_features=extrapolated,
    )
