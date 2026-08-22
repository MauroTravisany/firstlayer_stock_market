"""Stable facade for mandatory Yahoo row quarantine."""

from __future__ import annotations

from typing import Any

from tools import wp04_primary_source_quality_core as _core

POLICY_VERSION = _core.POLICY_VERSION
PROVIDER = _core.PROVIDER
MIN_VALID_ROW_RATIO = _core.MIN_VALID_ROW_RATIO
MAX_INVALID_ROWS_PER_SERIES = _core.MAX_INVALID_ROWS_PER_SERIES
PRICE_FIELDS = _core.PRICE_FIELDS
NY = _core.NY
UTC = _core.UTC
ProviderRowValidationError = _core.ProviderRowValidationError
PrimarySourceQualityError = _core.PrimarySourceQualityError
clean_price_payload = _core.clean_price_payload
normalize_yahoo_frame = _core.normalize_yahoo_frame

def __getattr__(name: str) -> Any:
    try:
        return getattr(_core, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc

def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_core)))
