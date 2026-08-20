"""Checksum-bound WP-04 planner with mandatory-primary row quarantine.

The reviewed provider-access behavior remains in
:mod:`tools.wp04_resilient_planner`. This facade prevents one malformed Yahoo
row from aborting an otherwise valid bounded series. Rejected primary rows are
never repaired or written as market data; they are captured in sanitized,
content-addressed JSONL artifacts and bound into the immutable plan checksum.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from packages.common.hashing import sha256_json
from tools import wp04_resilient_planner as _base
from tools.wp04_backfill_core import (
    Wp04BackfillError,
    canonical_json,
    finalize_plan,
    sha256_bytes,
)
from tools.wp04_primary_source_quality import (
    POLICY_VERSION as PRIMARY_SOURCE_POLICY_VERSION,
    PrimarySourceQualityError,
    ProviderRowValidationError,
    clean_price_payload,
    normalize_yahoo_frame,
)
from tools.wp04_secondary_source import SecondarySourceUnavailable


class _Collector:
    def __init__(self) -> None:
        self.status_rows: list[dict[str, Any]] = []
        self.rejection_rows: list[dict[str, Any]] = []


class _IngestionFacade:
    def __init__(self, delegate: Any, collector: _Collector) -> None:
        self._delegate = delegate
        self._collector = collector

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def yfinance_frame_records(self, frame: Any, **kwargs: Any) -> list[dict[str, Any]]:
        records, status, rejections = normalize_yahoo_frame(
            frame,
            normalizer=self._delegate.normalize_price_record,
            **kwargs,
        )
        self._collector.status_rows.append(status)
        self._collector.rejection_rows.extend(rejections)
        return records


def _write_status_jsonl(
    path: Path,
    rows: list[Mapping[str, Any]],
    *,
    identity_field: str,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    identities: list[str] = []
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            identity = str(row.get(identity_field) or "")
            if not identity:
                raise Wp04BackfillError(
                    f"{path.name} row is missing {identity_field}"
                )
            identities.append(identity)
            handle.write(canonical_json(row) + "\n")
    if len(identities) != len(set(identities)):
        raise Wp04BackfillError(
            f"duplicate {identity_field} generated in {path.name}"
        )
    raw = path.read_bytes()
    return {
        "path": path.as_posix(),
        "row_count": len(rows),
        "sha256": sha256_bytes(raw),
        "identity_set_sha256": sha256_json(sorted(identities)),
    }


def _validated_secondary_fetch(original_fetch: Any):
    def fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        symbol = str(args[0] if args else kwargs.get("symbol") or "")
        payloads = original_fetch(*args, **kwargs)
        cleaned: list[dict[str, Any]] = []
        try:
            for payload in payloads:
                cleaned.append(clean_price_payload(payload))
        except ProviderRowValidationError as exc:
            raise SecondarySourceUnavailable(
                "INVALID_OHLC",
                f"Stooq returned an invalid price row for {symbol}",
            ) from exc
        return cleaned

    return fetch


def build_plan(
    *,
    git_sha: str,
    asset_set_path: Path,
    tickers: str | None,
    start_date,
    end_date,
    intraday_start_date,
    hourly_start_date,
    max_rows: int,
    work_dir: Path,
    timeout_seconds: int,
    require_secondary_source: bool = False,
    stooq_api_key: str | None = None,
) -> dict[str, Any]:
    """Build the resilient plan and bind primary-row quarantine evidence."""

    collector = _Collector()
    original_loader = _base.base._load_ingestion_module
    original_secondary_fetch = _base.fetch_stooq_daily

    def load_ingestion() -> _IngestionFacade:
        return _IngestionFacade(original_loader(), collector)

    _base.base._load_ingestion_module = load_ingestion
    _base.fetch_stooq_daily = _validated_secondary_fetch(original_secondary_fetch)
    try:
        plan = _base.build_plan(
            git_sha=git_sha,
            asset_set_path=asset_set_path,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            intraday_start_date=intraday_start_date,
            hourly_start_date=hourly_start_date,
            max_rows=max_rows,
            work_dir=work_dir,
            timeout_seconds=timeout_seconds,
            require_secondary_source=require_secondary_source,
            stooq_api_key=stooq_api_key,
        )
    except PrimarySourceQualityError as exc:
        raise Wp04BackfillError(str(exc)) from exc
    finally:
        _base.base._load_ingestion_module = original_loader
        _base.fetch_stooq_daily = original_secondary_fetch

    if not collector.status_rows:
        raise Wp04BackfillError(
            "primary-source policy produced no mandatory series status rows"
        )

    status_file = _write_status_jsonl(
        work_dir / "primary_source_status.jsonl",
        collector.status_rows,
        identity_field="status_id",
    )
    rejection_file = _write_status_jsonl(
        work_dir / "primary_source_rejections.jsonl",
        collector.rejection_rows,
        identity_field="rejection_id",
    )

    files = dict(plan["files"])
    files.update(
        {
            "primary_source_status": status_file,
            "primary_source_rejections": rejection_file,
        }
    )
    total_row_count = sum(int(row["row_count"]) for row in files.values())
    if total_row_count > int(max_rows):
        raise Wp04BackfillError(
            "complete plan plus quarantine evidence exceeds max_rows"
        )

    provider_versions = dict(plan["provider_versions"])
    provider_versions["PRIMARY_SOURCE_POLICY"] = PRIMARY_SOURCE_POLICY_VERSION
    result = {
        **plan,
        "files": files,
        "total_row_count": total_row_count,
        "provider_versions": provider_versions,
        "primary_source_policy": {
            "policy_version": PRIMARY_SOURCE_POLICY_VERSION,
            "provider": "YAHOO",
            "required": True,
            "series_status_count": len(collector.status_rows),
            "rejected_row_count": len(collector.rejection_rows),
            "disposition": "QUARANTINE_WITHOUT_REPAIR",
            "production_change_allowed": False,
        },
        "production_change_allowed": False,
    }
    return finalize_plan(result)
