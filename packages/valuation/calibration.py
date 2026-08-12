"""Calibration diagnostics for valuation probabilities and intervals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .models import ValuationError


@dataclass(frozen=True)
class ProbabilityForecast:
    probability: float
    outcome: bool
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.probability)) or not 0 <= self.probability <= 1:
            raise ValuationError("probability must be between 0 and 1")
        if not math.isfinite(float(self.weight)) or self.weight <= 0:
            raise ValuationError("forecast weight must be positive")


@dataclass(frozen=True)
class IntervalForecast:
    lower: float
    upper: float
    realized: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        for label, value in (
            ("lower", self.lower),
            ("upper", self.upper),
            ("realized", self.realized),
            ("weight", self.weight),
        ):
            if not math.isfinite(float(value)):
                raise ValuationError(f"{label} must be finite")
        if self.lower > self.upper:
            raise ValuationError("interval lower cannot exceed upper")
        if self.weight <= 0:
            raise ValuationError("interval weight must be positive")


@dataclass(frozen=True)
class CalibrationBin:
    lower_bound: float
    upper_bound: float
    count: int
    total_weight: float
    mean_probability: float
    empirical_frequency: float
    absolute_gap: float


@dataclass(frozen=True)
class ProbabilityCalibrationReport:
    sample_size: int
    total_weight: float
    positive_rate: float
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    maximum_calibration_error: float
    bins: tuple[CalibrationBin, ...]
    status: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class IntervalCalibrationReport:
    sample_size: int
    total_weight: float
    empirical_coverage: float
    target_coverage: float
    coverage_gap: float
    mean_interval_width: float
    status: str
    reason_codes: tuple[str, ...]


def probability_calibration_report(
    forecasts: Sequence[ProbabilityForecast],
    *,
    bins: int = 10,
    min_samples: int = 100,
    max_ece: float = 0.10,
    max_brier: float = 0.25,
) -> ProbabilityCalibrationReport:
    if bins < 2:
        raise ValuationError("bins must be >= 2")
    if min_samples < 1:
        raise ValuationError("min_samples must be positive")
    if not 0 <= max_ece <= 1 or not 0 <= max_brier <= 1:
        raise ValuationError("calibration thresholds must be between 0 and 1")
    if not forecasts:
        return ProbabilityCalibrationReport(
            sample_size=0,
            total_weight=0.0,
            positive_rate=0.0,
            brier_score=0.0,
            log_loss=0.0,
            expected_calibration_error=0.0,
            maximum_calibration_error=0.0,
            bins=(),
            status="INSUFFICIENT",
            reason_codes=("NO_CALIBRATION_OBSERVATIONS",),
        )

    total_weight = sum(item.weight for item in forecasts)
    positive_rate = (
        sum(item.weight * float(item.outcome) for item in forecasts) / total_weight
    )
    brier = (
        sum(
            item.weight * (item.probability - float(item.outcome)) ** 2
            for item in forecasts
        )
        / total_weight
    )
    epsilon = 1e-15
    log_loss = -sum(
        item.weight
        * (
            float(item.outcome)
            * math.log(max(item.probability, epsilon))
            + (1.0 - float(item.outcome))
            * math.log(max(1.0 - item.probability, epsilon))
        )
        for item in forecasts
    ) / total_weight

    calibration_bins: list[CalibrationBin] = []
    ece = 0.0
    maximum_gap = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            item
            for item in forecasts
            if (
                lower <= item.probability < upper
                or (index == bins - 1 and item.probability == 1.0)
            )
        ]
        if not members:
            continue
        member_weight = sum(item.weight for item in members)
        mean_probability = (
            sum(item.weight * item.probability for item in members) / member_weight
        )
        empirical_frequency = (
            sum(item.weight * float(item.outcome) for item in members) / member_weight
        )
        gap = abs(mean_probability - empirical_frequency)
        ece += member_weight / total_weight * gap
        maximum_gap = max(maximum_gap, gap)
        calibration_bins.append(
            CalibrationBin(
                lower_bound=lower,
                upper_bound=upper,
                count=len(members),
                total_weight=member_weight,
                mean_probability=mean_probability,
                empirical_frequency=empirical_frequency,
                absolute_gap=gap,
            )
        )

    reasons: list[str] = []
    if len(forecasts) < min_samples:
        status = "INSUFFICIENT"
        reasons.append("CALIBRATION_SAMPLE_TOO_SMALL")
    else:
        if ece > max_ece:
            reasons.append("EXPECTED_CALIBRATION_ERROR_TOO_HIGH")
        if brier > max_brier:
            reasons.append("BRIER_SCORE_TOO_HIGH")
        status = "PASS" if not reasons else "FAIL"
    return ProbabilityCalibrationReport(
        sample_size=len(forecasts),
        total_weight=total_weight,
        positive_rate=positive_rate,
        brier_score=brier,
        log_loss=log_loss,
        expected_calibration_error=ece,
        maximum_calibration_error=maximum_gap,
        bins=tuple(calibration_bins),
        status=status,
        reason_codes=tuple(reasons),
    )


def interval_calibration_report(
    forecasts: Sequence[IntervalForecast],
    *,
    target_coverage: float = 0.80,
    min_samples: int = 100,
    tolerance: float = 0.05,
) -> IntervalCalibrationReport:
    if not 0 < target_coverage < 1:
        raise ValuationError("target_coverage must be between 0 and 1")
    if min_samples < 1:
        raise ValuationError("min_samples must be positive")
    if not 0 <= tolerance < 1:
        raise ValuationError("tolerance must be in [0, 1)")
    if not forecasts:
        return IntervalCalibrationReport(
            sample_size=0,
            total_weight=0.0,
            empirical_coverage=0.0,
            target_coverage=target_coverage,
            coverage_gap=-target_coverage,
            mean_interval_width=0.0,
            status="INSUFFICIENT",
            reason_codes=("NO_INTERVAL_OBSERVATIONS",),
        )
    total_weight = sum(item.weight for item in forecasts)
    covered_weight = sum(
        item.weight
        for item in forecasts
        if item.lower <= item.realized <= item.upper
    )
    empirical_coverage = covered_weight / total_weight
    mean_width = (
        sum(item.weight * (item.upper - item.lower) for item in forecasts)
        / total_weight
    )
    gap = empirical_coverage - target_coverage
    reasons: list[str] = []
    if len(forecasts) < min_samples:
        status = "INSUFFICIENT"
        reasons.append("INTERVAL_CALIBRATION_SAMPLE_TOO_SMALL")
    elif abs(gap) > tolerance:
        status = "FAIL"
        reasons.append("INTERVAL_COVERAGE_OUTSIDE_TOLERANCE")
    else:
        status = "PASS"
    return IntervalCalibrationReport(
        sample_size=len(forecasts),
        total_weight=total_weight,
        empirical_coverage=empirical_coverage,
        target_coverage=target_coverage,
        coverage_gap=gap,
        mean_interval_width=mean_width,
        status=status,
        reason_codes=tuple(reasons),
    )


def conformal_absolute_error(
    realized: Sequence[float],
    predicted_median: Sequence[float],
    *,
    coverage: float = 0.80,
) -> float:
    if len(realized) != len(predicted_median) or not realized:
        raise ValuationError(
            "realized and predicted_median must be non-empty and equally sized"
        )
    if not 0 < coverage < 1:
        raise ValuationError("coverage must be between 0 and 1")
    errors = sorted(
        abs(float(actual) - float(predicted))
        for actual, predicted in zip(realized, predicted_median)
    )
    if any(not math.isfinite(error) for error in errors):
        raise ValuationError("conformal residuals must be finite")
    rank = math.ceil((len(errors) + 1) * coverage) - 1
    rank = max(0, min(rank, len(errors) - 1))
    return errors[rank]


def apply_conformal_interval(
    *,
    median: float,
    raw_lower: float,
    raw_upper: float,
    absolute_error: float,
) -> tuple[float, float]:
    for label, value in (
        ("median", median),
        ("raw_lower", raw_lower),
        ("raw_upper", raw_upper),
        ("absolute_error", absolute_error),
    ):
        if not math.isfinite(float(value)):
            raise ValuationError(f"{label} must be finite")
    if raw_lower > median or raw_upper < median:
        raise ValuationError("raw interval must contain the median")
    if absolute_error < 0:
        raise ValuationError("absolute_error cannot be negative")
    lower = min(raw_lower, median - absolute_error)
    upper = max(raw_upper, median + absolute_error)
    return lower, upper
