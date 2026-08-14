"""Audit-grade market-data primitives for WP-04."""

from .calendar import iter_sessions, session_for_date
from .canonical import canonicalize_crypto_4h, canonicalize_session, total_return
from .models import (
    CanonicalBar,
    CorporateAction,
    RawPriceObservation,
    ReconciliationResult,
    SessionSpec,
)
from .reconciliation import reconcile_bars

__all__ = [
    "CanonicalBar",
    "CorporateAction",
    "RawPriceObservation",
    "ReconciliationResult",
    "SessionSpec",
    "session_for_date",
    "iter_sessions",
    "canonicalize_session",
    "canonicalize_crypto_4h",
    "total_return",
    "reconcile_bars",
]
