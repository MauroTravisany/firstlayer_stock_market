"""Fail-closed routing of valuation models by economic entity type."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .models import ModelDistribution


class EntityType(str, Enum):
    GENERAL_CORPORATE = "GENERAL_CORPORATE"
    BANK_INSURER = "BANK_INSURER"
    HIGH_GROWTH = "HIGH_GROWTH"
    CYCLICAL_COMMODITY = "CYCLICAL_COMMODITY"
    REIT = "REIT"
    ETF = "ETF"
    CRYPTO = "CRYPTO"


@dataclass(frozen=True)
class RouteDefinition:
    entity_type: EntityType
    required_groups: tuple[tuple[str, ...], ...]
    allowed_prefixes: tuple[str, ...]
    forbidden_prefixes: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class RouteValidation:
    entity_type: EntityType
    status: str
    matched_groups: tuple[tuple[str, ...], ...]
    missing_groups: tuple[tuple[str, ...], ...]
    forbidden_models: tuple[str, ...]
    reason_codes: tuple[str, ...]


ROUTES = {
    EntityType.GENERAL_CORPORATE: RouteDefinition(
        entity_type=EntityType.GENERAL_CORPORATE,
        required_groups=(("relative_",), ("fcff", "fcfe", "residual_income")),
        allowed_prefixes=(
            "relative_",
            "fcff",
            "fcfe",
            "residual_income",
            "dividend_discount",
        ),
        description="Non-financial operating company.",
    ),
    EntityType.BANK_INSURER: RouteDefinition(
        entity_type=EntityType.BANK_INSURER,
        required_groups=(("relative_pb",), ("residual_income",)),
        allowed_prefixes=(
            "relative_pb",
            "residual_income",
            "dividend_discount",
        ),
        forbidden_prefixes=("relative_ev_", "fcff"),
        description="Financial institution valued from equity/book economics.",
    ),
    EntityType.HIGH_GROWTH: RouteDefinition(
        entity_type=EntityType.HIGH_GROWTH,
        required_groups=(("relative_ps",), ("fcff", "fcfe")),
        allowed_prefixes=(
            "relative_ps",
            "relative_p_fcf",
            "fcff",
            "fcfe",
            "residual_income",
        ),
        description="High-growth company; reverse DCF is a diagnostic, not a vote.",
    ),
    EntityType.CYCLICAL_COMMODITY: RouteDefinition(
        entity_type=EntityType.CYCLICAL_COMMODITY,
        required_groups=(("relative_ev_ebitda",), ("fcff",)),
        allowed_prefixes=("relative_ev_ebitda", "fcff"),
        description="Cyclical business requiring normalized cash-flow inputs.",
    ),
    EntityType.REIT: RouteDefinition(
        entity_type=EntityType.REIT,
        required_groups=(("reit_nav",), ("affo",)),
        allowed_prefixes=("reit_nav", "affo"),
        forbidden_prefixes=("relative_pe", "fcff"),
        description="REIT route based on NAV and AFFO.",
    ),
    EntityType.ETF: RouteDefinition(
        entity_type=EntityType.ETF,
        required_groups=(("etf_nav",),),
        allowed_prefixes=("etf_nav", "tracking_value"),
        forbidden_prefixes=(
            "relative_pe",
            "relative_pb",
            "relative_ps",
            "fcff",
            "residual_income",
        ),
        description="ETF route based on NAV, tracking and liquidity.",
    ),
    EntityType.CRYPTO: RouteDefinition(
        entity_type=EntityType.CRYPTO,
        required_groups=(("crypto_network",),),
        allowed_prefixes=("crypto_network", "crypto_liquidity"),
        forbidden_prefixes=(
            "relative_pe",
            "relative_pb",
            "relative_ps",
            "relative_ev_",
            "fcff",
            "residual_income",
        ),
        description="Digital-asset route; corporate accounting models do not apply.",
    ),
}


def _matches(family: str, prefixes: tuple[str, ...]) -> bool:
    normalized = family.lower()
    return any(normalized.startswith(prefix.lower()) for prefix in prefixes)


def validate_model_route(
    entity_type: EntityType,
    models: Sequence[ModelDistribution],
) -> RouteValidation:
    definition = ROUTES[entity_type]
    families = tuple(model.model_family.lower() for model in models)
    matched_groups = tuple(
        group for group in definition.required_groups if any(
            _matches(family, group) for family in families
        )
    )
    missing_groups = tuple(
        group for group in definition.required_groups if group not in matched_groups
    )
    forbidden_models = tuple(
        sorted(
            model.model_name
            for model in models
            if _matches(model.model_family, definition.forbidden_prefixes)
        )
    )
    disallowed_models = tuple(
        sorted(
            model.model_name
            for model in models
            if not _matches(model.model_family, definition.allowed_prefixes)
        )
    )
    reasons = []
    if missing_groups:
        reasons.append("VALUATION_ROUTE_REQUIRED_MODEL_MISSING")
    if forbidden_models:
        reasons.append("VALUATION_ROUTE_FORBIDDEN_MODEL")
    if disallowed_models:
        reasons.append("VALUATION_ROUTE_UNRECOGNIZED_MODEL")
    return RouteValidation(
        entity_type=entity_type,
        status="PASS" if not reasons else "FAIL",
        matched_groups=matched_groups,
        missing_groups=missing_groups,
        forbidden_models=tuple(sorted(set(forbidden_models + disallowed_models))),
        reason_codes=tuple(reasons),
    )
