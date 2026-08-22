"""Provider reconciliation and material-mismatch quality gates."""

from __future__ import annotations

from .models import CanonicalBar, ReconciliationResult


def reconcile_bars(
    primary: CanonicalBar,
    secondary: CanonicalBar | None,
    *,
    close_tolerance_bps: float = 10.0,
    volume_tolerance_ratio: float = 0.10,
    stale_after_seconds: int = 86_400,
) -> ReconciliationResult:
    if (
        close_tolerance_bps < 0
        or volume_tolerance_ratio < 0
        or stale_after_seconds <= 0
    ):
        raise ValueError(
            "reconciliation tolerances must be non-negative and stale window positive"
        )
    if secondary is None:
        return ReconciliationResult(
            primary.ticker,
            primary.session_date,
            primary.provider,
            None,
            "SOURCE_MISSING",
            None,
            None,
            True,
            "secondary provider missing",
        )
    if (
        primary.ticker,
        primary.session_date,
        primary.canonical_interval,
        primary.currency,
    ) != (
        secondary.ticker,
        secondary.session_date,
        secondary.canonical_interval,
        secondary.currency,
    ):
        raise ValueError("providers refer to different canonical observations")

    lag = abs((primary.available_at - secondary.available_at).total_seconds())
    if lag > stale_after_seconds:
        return ReconciliationResult(
            primary.ticker,
            primary.session_date,
            primary.provider,
            secondary.provider,
            "STALE_SOURCE",
            None,
            None,
            True,
            "provider availability timestamps are too far apart",
        )

    midpoint = (primary.adjusted_close + secondary.adjusted_close) / 2.0
    close_diff_bps = (
        abs(primary.adjusted_close - secondary.adjusted_close)
        / midpoint
        * 10_000.0
    )
    volume_diff_ratio = None
    if primary.raw_volume is not None and secondary.raw_volume is not None:
        denominator = max(primary.raw_volume, secondary.raw_volume, 1.0)
        volume_diff_ratio = (
            abs(primary.raw_volume - secondary.raw_volume) / denominator
        )

    if close_diff_bps == 0 and (
        volume_diff_ratio is None or volume_diff_ratio == 0
    ):
        status = "MATCH"
    elif close_diff_bps <= close_tolerance_bps and (
        volume_diff_ratio is None
        or volume_diff_ratio <= volume_tolerance_ratio
    ):
        status = "WITHIN_TOLERANCE"
    else:
        status = "MATERIAL_MISMATCH"

    return ReconciliationResult(
        ticker=primary.ticker,
        session_date=primary.session_date,
        primary_provider=primary.provider,
        secondary_provider=secondary.provider,
        status=status,
        close_diff_bps=close_diff_bps,
        volume_diff_ratio=volume_diff_ratio,
        blocks_quality=status == "MATERIAL_MISMATCH",
        reason=(
            "provider observations reconcile"
            if status in {"MATCH", "WITHIN_TOLERANCE"}
            else "price or volume difference exceeds tolerance"
        ),
    )
