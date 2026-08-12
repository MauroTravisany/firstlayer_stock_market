"""Peer-conditioned relative valuation with out-of-sample residual uncertainty."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from packages.common.hashing import sha256_json

from .models import (
    Applicability,
    CalibrationStatus,
    ModelDistribution,
    PriceObservation,
    ValuationError,
    ValuationLineage,
)
from .policy import ValuationPolicy

RELATIVE_MODEL_VERSION = "relative-ridge-loo-v2"


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
    price: PriceObservation
    features: Mapping[str, float]
    anchor_per_share: float | None = None
    enterprise_anchor: float | None = None
    net_debt: float = 0.0
    shares_outstanding: float | None = None

    def __post_init__(self) -> None:
        if not str(self.ticker).strip():
            raise ValuationError("subject ticker is required")
        if not isinstance(self.metric, RelativeMetric):
            raise ValuationError("metric is invalid")
        if not isinstance(self.price, PriceObservation):
            raise ValuationError("price must be a PriceObservation")
        if not self.features:
            raise ValuationError("subject features cannot be empty")
        for name, value in self.features.items():
            if not str(name).strip():
                raise ValuationError("subject feature name cannot be empty")
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
    peer_universe_hash: str
    configuration_hash: str
    extrapolated_features: tuple[str, ...] = ()
    validation_method: str = "LEAVE_ONE_OUT"


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


def _solve_linear_system(
    matrix: list[list[float]], vector: list[float]
) -> list[float]:
    size = len(vector)
    if len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValuationError("linear system dimensions are inconsistent")
    augmented = [
        [float(value) for value in matrix[row]] + [float(vector[row])]
        for row in range(size)
    ]
    for column in range(size):
        pivot = max(
            range(column, size),
            key=lambda row: abs(augmented[row][column]),
        )
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


def build_peer_universe_hash(peers: Sequence[PeerObservation]) -> str:
    """Hash the exact peer observations after deterministic ordering."""

    normalized_tickers = [peer.ticker.strip().upper() for peer in peers]
    if len(set(normalized_tickers)) != len(normalized_tickers):
        raise ValuationError("peer tickers must be unique")
    return sha256_json(
        [
            {
                "ticker": peer.ticker.strip().upper(),
                "observed_multiple": float(peer.observed_multiple),
                "features": {
                    name: float(peer.features[name]) for name in sorted(peer.features)
                },
            }
            for peer in sorted(peers, key=lambda row: row.ticker.strip().upper())
        ]
    )


def build_relative_configuration_hash(
    metric: RelativeMetric,
    feature_names: Sequence[str],
    policy: ValuationPolicy,
) -> str:
    names = tuple(sorted(str(name).strip() for name in feature_names))
    if not names or any(not name for name in names):
        raise ValuationError("relative feature names are invalid")
    if len(set(names)) != len(names):
        raise ValuationError("relative feature names must be unique")
    return sha256_json(
        {
            "model_version": RELATIVE_MODEL_VERSION,
            "metric": metric.value,
            "feature_names": names,
            "target_transform": "LOG_MULTIPLE",
            "scaler": "MEDIAN_MAD_WITH_PSTDEV_FALLBACK",
            "regression": "RIDGE_UNPENALIZED_INTERCEPT",
            "uncertainty": "LEAVE_ONE_OUT_EMPIRICAL_RESIDUALS",
            "ridge_penalty": policy.ridge_penalty,
            "min_peer_count": policy.min_peer_count,
            "min_peer_observations_per_parameter": (
                policy.min_peer_observations_per_parameter
            ),
            "relative_feature_z_limit": policy.relative_feature_z_limit,
        }
    )


def _fit_model(
    peers: Sequence[PeerObservation],
    feature_names: tuple[str, ...],
    penalty: float,
):
    centers: dict[str, float] = {}
    scales: dict[str, float] = {}
    for feature in feature_names:
        centers[feature], scales[feature] = _robust_center_scale(
            [float(peer.features[feature]) for peer in peers]
        )

    def encode(features: Mapping[str, float]) -> list[float]:
        return [1.0] + [
            (float(features[name]) - centers[name]) / scales[name]
            for name in feature_names
        ]

    design = [encode(peer.features) for peer in peers]
    target = [math.log(float(peer.observed_multiple)) for peer in peers]
    coefficients = _ridge_coefficients(design, target, penalty)
    fitted = [_dot(row, coefficients) for row in design]
    residual_center = _median(
        [actual - prediction for actual, prediction in zip(target, fitted)]
    )
    return centers, scales, coefficients, residual_center, target


def _encode(
    features: Mapping[str, float],
    feature_names: tuple[str, ...],
    centers: Mapping[str, float],
    scales: Mapping[str, float],
) -> list[float]:
    return [1.0] + [
        (float(features[name]) - centers[name]) / scales[name]
        for name in feature_names
    ]


def _observed_multiple(subject: RelativeSubject) -> float:
    if subject.metric is RelativeMetric.EV_EBITDA:
        enterprise_value = (
            subject.price.price * float(subject.shares_outstanding)
            + float(subject.net_debt)
        )
        multiple = enterprise_value / float(subject.enterprise_anchor)
    else:
        multiple = subject.price.price / float(subject.anchor_per_share)
    if not math.isfinite(multiple) or multiple <= 0:
        raise ValuationError("subject observed multiple must be positive")
    return multiple


def _implied_price(subject: RelativeSubject, predicted_multiple: float) -> float:
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
    """Estimate fair value from peers using leave-one-out residual uncertainty."""

    lineage.assert_price_compatible(subject.price)
    feature_names = tuple(sorted(subject.features))
    if not feature_names:
        raise ValuationError("at least one relative valuation feature is required")
    expected_configuration_hash = build_relative_configuration_hash(
        subject.metric, feature_names, policy
    )
    if lineage.model_version != RELATIVE_MODEL_VERSION:
        raise ValuationError("relative lineage model_version is incompatible")
    if lineage.configuration_hash != expected_configuration_hash:
        raise ValuationError("relative lineage configuration_hash is incompatible")

    minimum_peers = policy.minimum_peer_observations(len(feature_names))
    if len(peers) < minimum_peers:
        raise ValuationError(
            f"relative valuation requires at least {minimum_peers} peers "
            f"for {len(feature_names)} features"
        )
    peer_tickers = [peer.ticker.strip().upper() for peer in peers]
    if len(set(peer_tickers)) != len(peer_tickers):
        raise ValuationError("peer tickers must be unique")
    if subject.ticker.strip().upper() in set(peer_tickers):
        raise ValuationError("subject ticker cannot be included in its peer regression")
    peer_hash = build_peer_universe_hash(peers)
    if lineage.peer_universe_hash is None:
        raise ValuationError("relative valuation lineage requires peer_universe_hash")
    if lineage.peer_universe_hash != peer_hash:
        raise ValuationError(
            "peer_universe_hash does not match supplied peer observations"
        )

    for peer in peers:
        missing = sorted(set(feature_names) - set(peer.features))
        extra = sorted(set(peer.features) - set(feature_names))
        if missing or extra:
            raise ValuationError(
                f"peer {peer.ticker} feature mismatch; missing={missing}, extra={extra}"
            )

    centers, scales, coefficients, _bias, target = _fit_model(
        peers, feature_names, policy.ridge_penalty
    )
    loo_predictions: list[float] = []
    loo_residuals: list[float] = []
    for index, peer in enumerate(peers):
        training = tuple(peers[:index]) + tuple(peers[index + 1 :])
        loo_centers, loo_scales, loo_coefficients, loo_bias, _ = _fit_model(
            training, feature_names, policy.ridge_penalty
        )
        prediction = (
            _dot(
                _encode(peer.features, feature_names, loo_centers, loo_scales),
                loo_coefficients,
            )
            + loo_bias
        )
        actual = math.log(float(peer.observed_multiple))
        loo_predictions.append(prediction)
        loo_residuals.append(actual - prediction)

    residual_center, residual_scale = _robust_center_scale(loo_residuals)
    centered_residuals = [residual - residual_center for residual in loo_residuals]
    subject_vector = _encode(subject.features, feature_names, centers, scales)
    predicted_log_multiple = _dot(subject_vector, coefficients) + residual_center
    predicted_multiple = math.exp(predicted_log_multiple)
    observed_multiple = _observed_multiple(subject)
    log_residual = math.log(observed_multiple) - predicted_log_multiple
    robust_residual_z = -log_residual / residual_scale

    residual_quantiles = [
        _quantile(centered_residuals, probability)
        for probability in (0.10, 0.25, 0.50, 0.75, 0.90)
    ]
    fair_values = [
        _implied_price(subject, math.exp(predicted_log_multiple + residual))
        for residual in residual_quantiles
    ]

    target_mean = sum(target) / len(target)
    total_sum_squares = sum((value - target_mean) ** 2 for value in target)
    residual_sum_squares = sum(
        (actual - prediction) ** 2
        for actual, prediction in zip(target, loo_predictions)
    )
    r_squared = (
        1.0 - residual_sum_squares / total_sum_squares
        if total_sum_squares > 1e-12
        else 0.0
    )
    rmse = math.sqrt(residual_sum_squares / len(loo_residuals))
    sample_factor = min(1.0, len(peers) / (2.0 * minimum_peers))
    dispersion_factor = 1.0 / (1.0 + rmse)
    fit_factor = max(0.0, min(1.0, (r_squared + 1.0) / 2.0))
    confidence = min(
        0.75,
        max(
            0.0,
            sample_factor * dispersion_factor * (0.40 + 0.60 * fit_factor),
        ),
    )

    extrapolated = tuple(
        name
        for name, encoded_value in zip(feature_names, subject_vector[1:])
        if abs(encoded_value) > policy.relative_feature_z_limit
    )
    reasons = [
        "LEAVE_ONE_OUT_RESIDUAL_UNCERTAINTY",
        "MODEL_REQUIRES_OOS_CALIBRATION",
    ]
    if extrapolated:
        confidence *= 0.65
        reasons.append("SUBJECT_FEATURE_EXTRAPOLATION")
    if r_squared < 0:
        reasons.append("WEAK_OUT_OF_SAMPLE_RELATIVE_FIT")
    if residual_scale > 0.75:
        reasons.append("WIDE_PEER_MULTIPLE_DISPERSION")

    family = f"relative_{subject.metric.value.lower()}"
    distribution = ModelDistribution(
        model_name=f"{family}_ridge_loo_v2",
        model_family=family,
        p10=fair_values[0],
        p25=fair_values[1],
        p50=fair_values[2],
        p75=fair_values[3],
        p90=fair_values[4],
        confidence=round(confidence, 12),
        lineage=lineage,
        applicability=Applicability.APPLICABLE,
        score=robust_residual_z,
        calibration_status=CalibrationStatus.UNVERIFIED,
        calibration_hash=None,
        reason_codes=tuple(sorted(reasons)),
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
        peer_universe_hash=peer_hash,
        configuration_hash=expected_configuration_hash,
        extrapolated_features=extrapolated,
        validation_method="LEAVE_ONE_OUT",
    )
