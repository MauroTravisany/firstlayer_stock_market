"""Intrinsic valuation models with explicit scenarios and uncertainty."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

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

DCF_MODEL_VERSION = "fcff-scenario-v2"
RESIDUAL_INCOME_MODEL_VERSION = "residual-income-scenario-v2"


@dataclass(frozen=True)
class DcfScenario:
    name: str
    base_fcff: float
    growth_rates: tuple[float, ...]
    discount_rate: float
    terminal_growth_rate: float
    net_debt: float
    shares_outstanding: float
    probability: float

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValuationError("DCF scenario name is required")
        if not math.isfinite(float(self.base_fcff)) or self.base_fcff <= 0:
            raise ValuationError("base_fcff must be positive")
        if not self.growth_rates:
            raise ValuationError("at least one explicit DCF year is required")
        if any(
            not math.isfinite(float(growth)) or growth <= -1
            for growth in self.growth_rates
        ):
            raise ValuationError(
                "DCF growth rates must be finite and greater than -1"
            )
        _validate_discount_terminal(self.discount_rate, self.terminal_growth_rate)
        if not math.isfinite(float(self.net_debt)):
            raise ValuationError("net_debt must be finite")
        if (
            not math.isfinite(float(self.shares_outstanding))
            or self.shares_outstanding <= 0
        ):
            raise ValuationError("shares_outstanding must be positive")
        _validate_probability(self.probability)


@dataclass(frozen=True)
class ResidualIncomeScenario:
    name: str
    book_value_per_share: float
    roe_path: tuple[float, ...]
    cost_of_equity: float
    payout_ratio: float
    terminal_residual_growth: float
    probability: float

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValuationError("residual-income scenario name is required")
        if (
            not math.isfinite(float(self.book_value_per_share))
            or self.book_value_per_share <= 0
        ):
            raise ValuationError("book_value_per_share must be positive")
        if not self.roe_path:
            raise ValuationError("roe_path cannot be empty")
        if any(not math.isfinite(float(roe)) for roe in self.roe_path):
            raise ValuationError("ROE values must be finite")
        if not 0 < self.cost_of_equity < 1:
            raise ValuationError("cost_of_equity must be between 0 and 1")
        if not 0 <= self.payout_ratio <= 1:
            raise ValuationError("payout_ratio must be between 0 and 1")
        if self.terminal_residual_growth >= self.cost_of_equity:
            raise ValuationError(
                "terminal residual growth must be below cost_of_equity"
            )
        if self.terminal_residual_growth <= -1:
            raise ValuationError(
                "terminal residual growth must be greater than -1"
            )
        _validate_probability(self.probability)


@dataclass(frozen=True)
class ReverseDcfResult:
    implied_growth_rate: float
    target_price: float
    reproduced_price: float
    absolute_error: float
    iterations: int
    feasible: bool


def _validate_probability(value: float) -> None:
    if not math.isfinite(float(value)) or not 0 < value <= 1:
        raise ValuationError("scenario probability must be in (0, 1]")


def _validate_scenario_set(scenarios: Sequence[object]) -> None:
    if len(scenarios) < 3:
        raise ValuationError("scenario distribution requires at least three scenarios")
    names = [str(getattr(scenario, "name")).strip().lower() for scenario in scenarios]
    if len(set(names)) != len(names):
        raise ValuationError("scenario names must be unique")
    probability_sum = sum(
        float(getattr(scenario, "probability")) for scenario in scenarios
    )
    if not math.isclose(probability_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValuationError("scenario probabilities must sum to 1")


def _validate_discount_terminal(
    discount_rate: float, terminal_growth_rate: float
) -> None:
    if not math.isfinite(float(discount_rate)) or not 0 < discount_rate < 1:
        raise ValuationError("discount_rate must be between 0 and 1")
    if not math.isfinite(float(terminal_growth_rate)):
        raise ValuationError("terminal_growth_rate must be finite")
    if terminal_growth_rate <= -1:
        raise ValuationError("terminal_growth_rate must be greater than -1")
    if terminal_growth_rate >= discount_rate:
        raise ValuationError("terminal_growth_rate must be below discount_rate")


def build_dcf_configuration_hash(
    scenarios: Sequence[DcfScenario], policy: ValuationPolicy
) -> str:
    _validate_scenario_set(scenarios)
    return sha256_json(
        {
            "model_version": DCF_MODEL_VERSION,
            "valuation_method": "FCFF_TWO_STAGE_GORDON_TERMINAL",
            "scenario_quantiles": [0.10, 0.25, 0.50, 0.75, 0.90],
            "scenarios": tuple(sorted(scenarios, key=lambda item: item.name.lower())),
            "model_weight": policy.weight_for("fcff"),
        }
    )


def build_residual_income_configuration_hash(
    scenarios: Sequence[ResidualIncomeScenario], policy: ValuationPolicy
) -> str:
    _validate_scenario_set(scenarios)
    return sha256_json(
        {
            "model_version": RESIDUAL_INCOME_MODEL_VERSION,
            "valuation_method": "CLEAN_SURPLUS_RESIDUAL_INCOME",
            "loss_dividend_policy": "ZERO_DIVIDEND_ON_NEGATIVE_EARNINGS",
            "scenario_quantiles": [0.10, 0.25, 0.50, 0.75, 0.90],
            "scenarios": tuple(sorted(scenarios, key=lambda item: item.name.lower())),
            "model_weight": policy.weight_for("residual_income"),
        }
    )


def discounted_cash_flow_value(scenario: DcfScenario) -> float:
    """Return per-share equity value for one FCFF scenario."""

    cash_flow = float(scenario.base_fcff)
    enterprise_value = 0.0
    for year, growth_rate in enumerate(scenario.growth_rates, start=1):
        cash_flow *= 1.0 + float(growth_rate)
        enterprise_value += cash_flow / ((1.0 + scenario.discount_rate) ** year)
    terminal_cash_flow = cash_flow * (1.0 + scenario.terminal_growth_rate)
    terminal_value = terminal_cash_flow / (
        scenario.discount_rate - scenario.terminal_growth_rate
    )
    enterprise_value += terminal_value / (
        (1.0 + scenario.discount_rate) ** len(scenario.growth_rates)
    )
    equity_value = enterprise_value - scenario.net_debt
    per_share = equity_value / scenario.shares_outstanding
    if not math.isfinite(per_share) or per_share <= 0:
        raise ValuationError("DCF scenario implies non-positive equity value")
    return per_share


def residual_income_value(scenario: ResidualIncomeScenario) -> float:
    """Return per-share equity value using clean-surplus residual income."""

    opening_book = float(scenario.book_value_per_share)
    value = opening_book
    residual_income = 0.0
    for year, roe in enumerate(scenario.roe_path, start=1):
        earnings = float(roe) * opening_book
        residual_income = earnings - scenario.cost_of_equity * opening_book
        value += residual_income / ((1.0 + scenario.cost_of_equity) ** year)
        # A payout ratio is a distribution policy, not an assumed capital
        # injection. Losses therefore produce zero dividends.
        dividends = scenario.payout_ratio * max(earnings, 0.0)
        opening_book = opening_book + earnings - dividends
        if opening_book <= 0 or not math.isfinite(opening_book):
            raise ValuationError("residual-income book value became non-positive")
    next_residual_income = residual_income * (
        1.0 + scenario.terminal_residual_growth
    )
    terminal_value = next_residual_income / (
        scenario.cost_of_equity - scenario.terminal_residual_growth
    )
    value += terminal_value / (
        (1.0 + scenario.cost_of_equity) ** len(scenario.roe_path)
    )
    if not math.isfinite(value) or value <= 0:
        raise ValuationError("residual-income scenario implies non-positive value")
    return value


def _weighted_quantile(
    observations: Sequence[tuple[float, float]], probability: float
) -> float:
    if not observations:
        raise ValuationError("at least one scenario is required")
    if not 0 <= probability <= 1:
        raise ValuationError("quantile probability must be between 0 and 1")
    ordered = sorted((float(value), float(weight)) for value, weight in observations)
    if any(not math.isfinite(value) or value <= 0 for value, _ in ordered):
        raise ValuationError("scenario values must be positive")
    if any(not math.isfinite(weight) or weight <= 0 for _, weight in ordered):
        raise ValuationError("scenario weights must be positive")
    total = sum(weight for _, weight in ordered)
    threshold = probability * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _validate_model_lineage(
    lineage: ValuationLineage,
    expected_model_version: str,
    expected_configuration_hash: str,
    price: PriceObservation | None,
) -> None:
    if lineage.model_version != expected_model_version:
        raise ValuationError("intrinsic lineage model_version is incompatible")
    if lineage.configuration_hash != expected_configuration_hash:
        raise ValuationError("intrinsic lineage configuration_hash is incompatible")
    if lineage.peer_universe_hash is not None:
        raise ValuationError("intrinsic models cannot carry peer_universe_hash")
    if price is not None:
        lineage.assert_price_compatible(price)


def _distribution_from_values(
    *,
    model_name: str,
    model_family: str,
    values: Sequence[tuple[float, float]],
    confidence: float,
    lineage: ValuationLineage,
    current_price: float | None,
    reason_codes: tuple[str, ...],
) -> ModelDistribution:
    if not 0 <= confidence <= 1:
        raise ValuationError("confidence must be between 0 and 1")
    quantiles = [
        _weighted_quantile(values, probability)
        for probability in (0.10, 0.25, 0.50, 0.75, 0.90)
    ]
    score = None
    if current_price is not None:
        if not math.isfinite(float(current_price)) or current_price <= 0:
            raise ValuationError("current_price must be positive")
        width = max((quantiles[4] - quantiles[0]) / quantiles[2], 1e-6)
        score = math.log(quantiles[2] / current_price) / width
    return ModelDistribution(
        model_name=model_name,
        model_family=model_family,
        p10=quantiles[0],
        p25=quantiles[1],
        p50=quantiles[2],
        p75=quantiles[3],
        p90=quantiles[4],
        confidence=min(0.65, confidence),
        lineage=lineage,
        applicability=Applicability.APPLICABLE,
        score=score,
        calibration_status=CalibrationStatus.UNVERIFIED,
        calibration_hash=None,
        reason_codes=tuple(sorted(set(reason_codes))),
        production_change_allowed=False,
    )


def dcf_scenario_distribution(
    scenarios: Sequence[DcfScenario],
    lineage: ValuationLineage,
    policy: ValuationPolicy,
    *,
    price: PriceObservation | None = None,
    model_name: str = "fcff_scenario_ensemble_v2",
) -> ModelDistribution:
    _validate_scenario_set(scenarios)
    configuration_hash = build_dcf_configuration_hash(scenarios, policy)
    _validate_model_lineage(lineage, DCF_MODEL_VERSION, configuration_hash, price)
    values = [
        (discounted_cash_flow_value(scenario), scenario.probability)
        for scenario in scenarios
    ]
    scenario_factor = min(1.0, len(scenarios) / 5.0)
    structural_confidence = 0.35 + 0.30 * scenario_factor
    return _distribution_from_values(
        model_name=model_name,
        model_family="fcff",
        values=values,
        confidence=structural_confidence,
        lineage=lineage,
        current_price=price.price if price is not None else None,
        reason_codes=(
            "SCENARIO_DISTRIBUTION_REQUIRES_OOS_CALIBRATION",
            "SCENARIO_PROBABILITIES_SUM_TO_ONE",
        ),
    )


def residual_income_distribution(
    scenarios: Sequence[ResidualIncomeScenario],
    lineage: ValuationLineage,
    policy: ValuationPolicy,
    *,
    price: PriceObservation | None = None,
    model_name: str = "residual_income_scenario_ensemble_v2",
) -> ModelDistribution:
    _validate_scenario_set(scenarios)
    configuration_hash = build_residual_income_configuration_hash(scenarios, policy)
    _validate_model_lineage(
        lineage, RESIDUAL_INCOME_MODEL_VERSION, configuration_hash, price
    )
    values = [
        (residual_income_value(scenario), scenario.probability)
        for scenario in scenarios
    ]
    structural_confidence = min(0.65, 0.35 + 0.075 * len(scenarios))
    return _distribution_from_values(
        model_name=model_name,
        model_family="residual_income",
        values=values,
        confidence=structural_confidence,
        lineage=lineage,
        current_price=price.price if price is not None else None,
        reason_codes=(
            "SCENARIO_DISTRIBUTION_REQUIRES_OOS_CALIBRATION",
            "NEGATIVE_EARNINGS_DO_NOT_CREATE_NEGATIVE_DIVIDENDS",
            "SCENARIO_PROBABILITIES_SUM_TO_ONE",
        ),
    )


def _constant_growth_dcf_price(
    *,
    growth_rate: float,
    base_fcff: float,
    years: int,
    discount_rate: float,
    terminal_growth_rate: float,
    net_debt: float,
    shares_outstanding: float,
) -> float:
    if not math.isfinite(float(base_fcff)) or base_fcff <= 0:
        raise ValuationError("base_fcff must be positive")
    if not math.isfinite(float(growth_rate)) or growth_rate <= -1:
        raise ValuationError("growth_rate must be finite and greater than -1")
    if not math.isfinite(float(net_debt)):
        raise ValuationError("net_debt must be finite")
    if not math.isfinite(float(shares_outstanding)) or shares_outstanding <= 0:
        raise ValuationError("shares_outstanding must be positive")
    _validate_discount_terminal(discount_rate, terminal_growth_rate)
    cash_flow = float(base_fcff)
    enterprise_value = 0.0
    for year in range(1, years + 1):
        cash_flow *= 1.0 + growth_rate
        enterprise_value += cash_flow / ((1.0 + discount_rate) ** year)
    terminal_cash_flow = cash_flow * (1.0 + terminal_growth_rate)
    terminal_value = terminal_cash_flow / (
        discount_rate - terminal_growth_rate
    )
    enterprise_value += terminal_value / ((1.0 + discount_rate) ** years)
    return (enterprise_value - net_debt) / shares_outstanding


def reverse_dcf_growth(
    *,
    target_price: float,
    base_fcff: float,
    years: int,
    discount_rate: float,
    terminal_growth_rate: float,
    net_debt: float,
    shares_outstanding: float,
    lower_growth: float = -0.50,
    upper_growth: float = 1.00,
    tolerance: float = 1e-8,
    max_iterations: int = 200,
) -> ReverseDcfResult:
    """Solve the constant explicit growth rate implied by ``target_price``."""

    if not math.isfinite(float(target_price)) or target_price <= 0:
        raise ValuationError("target_price must be positive")
    if years < 1:
        raise ValuationError("years must be >= 1")
    if lower_growth <= -1 or lower_growth >= upper_growth:
        raise ValuationError("reverse DCF growth bounds are invalid")
    if tolerance <= 0 or max_iterations < 1:
        raise ValuationError("reverse DCF solver controls are invalid")
    _validate_discount_terminal(discount_rate, terminal_growth_rate)

    lower_price = _constant_growth_dcf_price(
        growth_rate=lower_growth,
        base_fcff=base_fcff,
        years=years,
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth_rate,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
    )
    upper_price = _constant_growth_dcf_price(
        growth_rate=upper_growth,
        base_fcff=base_fcff,
        years=years,
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth_rate,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
    )
    if not lower_price <= target_price <= upper_price:
        closest_growth, closest_price = (
            (lower_growth, lower_price)
            if abs(lower_price - target_price) <= abs(upper_price - target_price)
            else (upper_growth, upper_price)
        )
        return ReverseDcfResult(
            implied_growth_rate=closest_growth,
            target_price=target_price,
            reproduced_price=closest_price,
            absolute_error=abs(closest_price - target_price),
            iterations=0,
            feasible=False,
        )

    lower = lower_growth
    upper = upper_growth
    reproduced = lower_price
    midpoint = lower
    for iteration in range(1, max_iterations + 1):
        midpoint = (lower + upper) / 2.0
        reproduced = _constant_growth_dcf_price(
            growth_rate=midpoint,
            base_fcff=base_fcff,
            years=years,
            discount_rate=discount_rate,
            terminal_growth_rate=terminal_growth_rate,
            net_debt=net_debt,
            shares_outstanding=shares_outstanding,
        )
        error = reproduced - target_price
        if abs(error) <= tolerance:
            return ReverseDcfResult(
                implied_growth_rate=midpoint,
                target_price=target_price,
                reproduced_price=reproduced,
                absolute_error=abs(error),
                iterations=iteration,
                feasible=True,
            )
        if error < 0:
            lower = midpoint
        else:
            upper = midpoint
    return ReverseDcfResult(
        implied_growth_rate=midpoint,
        target_price=target_price,
        reproduced_price=reproduced,
        absolute_error=abs(reproduced - target_price),
        iterations=max_iterations,
        feasible=abs(reproduced - target_price) <= tolerance * 10,
    )
