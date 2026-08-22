import datetime as dt
import copy
import io
import logging
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import Mock

import requests

from tools import wp04_fx_source as source
from tools import wp04_shadow_backfill as retired
from tools import wp04_shadow_backfill_official_fx as executor
from tools import wp04_shadow_backfill_windowed as retired_windowed
from tools.wp04_backfill_core import finalize_plan, write_jsonl


ROOT = Path(__file__).resolve().parents[3]
ASSET_SET = ROOT / "config" / "wp04_shadow_assets.v1.json"
UTC = dt.timezone.utc


class Wp04VintageAvailabilityTests(unittest.TestCase):
    def test_revision_visibility_is_as_of_first_observation(self):
        t1 = dt.datetime(2026, 8, 20, 12, tzinfo=UTC)
        t2 = dt.datetime(2026, 8, 21, 12, tzinfo=UTC)
        initial = source._raw_row(
            rate_date=dt.date(2024, 1, 3),
            source_reference_date=dt.date(2024, 1, 2),
            rate=900.0,
            ingestion_run_id="run-t1",
            ingested_at=t1,
        )
        repeated = source._raw_row(
            rate_date=dt.date(2024, 1, 3),
            source_reference_date=dt.date(2024, 1, 2),
            rate=900.0,
            ingestion_run_id="run-repeat",
            ingested_at=t2,
        )
        corrected = source._raw_row(
            rate_date=dt.date(2024, 1, 3),
            source_reference_date=dt.date(2024, 1, 2),
            rate=901.0,
            ingestion_run_id="run-t2",
            ingested_at=t2,
        )

        self.assertEqual(initial["fx_rate_revision_id"], repeated["fx_rate_revision_id"])
        self.assertNotEqual(initial["fx_rate_revision_id"], corrected["fx_rate_revision_id"])
        self.assertEqual(t1, initial["first_observed_at"])
        self.assertEqual(t1, initial["available_at"])
        self.assertFalse(initial["backtest_eligible"])
        self.assertIsNone(
            source.select_revision_as_of([initial, corrected], t1 - dt.timedelta(seconds=1))
        )
        self.assertEqual(
            initial["fx_rate_revision_id"],
            source.select_revision_as_of(
                [corrected, initial], t1 + dt.timedelta(seconds=1)
            )["fx_rate_revision_id"],
        )
        self.assertEqual(
            corrected["fx_rate_revision_id"],
            source.select_revision_as_of(
                [initial, corrected], t2 + dt.timedelta(seconds=1)
            )["fx_rate_revision_id"],
        )

    def test_transport_exception_never_retains_token_in_chain_or_logging(self):
        token = "super-private-bcch-token"
        exception_types = (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.RetryError,
        )
        for exception_type in exception_types:
            with self.subTest(exception_type=exception_type.__name__):
                def fail(*_args, **_kwargs):
                    raise exception_type(
                        "GET https://example.invalid?"
                        f"token={token}&function=GetSeries"
                    )

                try:
                    source.fetch_bcch_observed_dollar(
                        token=token,
                        start_date=dt.date(2024, 1, 1),
                        end_date=dt.date(2024, 1, 2),
                        ingestion_run_id="run",
                        ingested_at=dt.datetime(2026, 8, 20, tzinfo=UTC),
                        get=fail,
                    )
                except source.OfficialFxSourceError as exc:
                    rendered = "".join(traceback.format_exception(exc))
                    chain = repr(exc.__cause__)
                    stream = io.StringIO()
                    handler = logging.StreamHandler(stream)
                    logger = logging.getLogger(
                        f"wp04-token-test-{exception_type.__name__}"
                    )
                    logger.handlers = [handler]
                    logger.propagate = False
                    logger.error(
                        "official source failed",
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )
                    handler.flush()
                    combined = rendered + repr(exc) + chain + stream.getvalue()
                    self.assertNotIn(token, combined)
                    self.assertIsNone(exc.__cause__)
                else:
                    self.fail("transport failure did not fail closed")


class Wp04RetiredEntrypointTests(unittest.TestCase):
    def test_runbook_exposes_only_official_fx_planning_and_execution(self):
        runbook = (
            ROOT
            / "docs"
            / "audit-grade"
            / "runbooks"
            / "WP-04_CANONICAL_PRICE_SHADOW_VALIDATION.md"
        ).read_text(encoding="utf-8")
        commands = [
            line.strip()
            for line in runbook.splitlines()
            if line.strip().startswith("python tools/wp04_shadow_backfill")
        ]
        self.assertEqual(
            {
                "python tools/wp04_shadow_backfill_windowed_official_fx.py \\",
                "python tools/wp04_shadow_backfill_official_fx.py \\",
            },
            set(commands),
        )
        self.assertNotIn("python tools/wp04_shadow_backfill.py", runbook)
        self.assertNotIn("python tools/wp04_shadow_backfill_windowed.py", runbook)
        for marker in ("11 required actions", "4 operations", "6 relations", "1 assertion"):
            self.assertIn(marker, runbook)

    def test_direct_and_windowed_legacy_planners_reject_asset_set_v2(self):
        kwargs = dict(
            git_sha="a" * 40,
            asset_set_path=ASSET_SET,
            tickers=None,
            start_date=dt.date(2024, 1, 1),
            end_date=dt.date(2024, 1, 2),
            intraday_start_date=dt.date(2024, 1, 1),
            hourly_start_date=dt.date(2024, 1, 1),
            max_rows=100,
            work_dir=Path("unused"),
            timeout_seconds=1,
        )
        with self.assertRaisesRegex(retired.Wp04BackfillError, "official-FX"):
            retired.build_plan(**kwargs)
        with self.assertRaisesRegex(retired.Wp04BackfillError, "official-FX"):
            retired_windowed.build_windowed_plan(
                git_sha="a" * 40,
                asset_set_path=ASSET_SET,
                tickers=None,
                daily_start_date=dt.date(2024, 1, 1),
                end_lag_days=2,
                intraday_lookback_days=45,
                hourly_lookback_days=365,
                max_rows=100,
                work_dir=Path("unused"),
                timeout_seconds=1,
                anchor_at=dt.datetime(2026, 8, 20, tzinfo=UTC),
            )

    def test_legacy_executor_rejects_official_fx_plan_before_bigquery(self):
        _version, assets, _checksum = retired.load_asset_set(ASSET_SET)
        plan = {"assets": list(assets), "files": {}}
        with self.assertRaisesRegex(retired.Wp04BackfillError, "official-FX"):
            retired.execute_plan(
                plan=plan,
                project_id="stocks-437902",
                dataset_id="acciones_dataset_shadow_wp04_test",
                location="us-east1",
            )


class Wp04ExecutorValidationTests(unittest.TestCase):
    def _plan(self, root: Path):
        observed = dt.datetime(2026, 8, 20, 12, tzinfo=UTC)
        row = source._raw_row(
            rate_date=dt.date(2024, 1, 3),
            source_reference_date=dt.date(2024, 1, 2),
            rate=900.0,
            ingestion_run_id="run",
            ingested_at=observed,
        )
        status = source.build_status_document(
            query_start_date=dt.date(2023, 11, 30),
            start_date=dt.date(2024, 1, 1),
            end_date=dt.date(2024, 1, 3),
            ingestion_run_id="run",
            accepted_row_count=1,
            skipped_status_counts={},
            observed_at=observed,
        )
        files = {
            "market_price_raw": write_jsonl(root / "market.jsonl", []),
            "corporate_actions_pit": write_jsonl(root / "actions.jsonl", []),
            "market_session_calendar": write_jsonl(root / "calendar.jsonl", []),
            "fx_rate_raw": write_jsonl(root / "fx.jsonl", [row]),
            "official_fx_source_status": write_jsonl(root / "status.jsonl", [status]),
        }
        plan = {
            "schema_version": 1,
            "operation": "WP04_SHADOW_BACKFILL",
            "git_sha": "a" * 40,
            "asset_set_version": "wp04-shadow-assets-2026-08-v2",
            "asset_set_sha256": "b" * 64,
            "assets": [],
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "intraday_start_date": "2024-01-01",
            "hourly_start_date": "2024-01-01",
            "files": files,
            "total_row_count": sum(item["row_count"] for item in files.values()),
            "max_rows": 100,
            "provider_versions": {
                "BCCH_BDE": source.SOURCE_VERSION,
                "OFFICIAL_FX_POLICY": source.POLICY_VERSION,
                "OFFICIAL_FX_AVAILABILITY_POLICY": source.AVAILABILITY_POLICY,
            },
            "official_fx_source_policy": source.official_source_policy(),
            "production_change_allowed": False,
        }
        return finalize_plan(plan)

    def test_tampered_semantics_fail_before_any_bigquery_client_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self._plan(root)
            row = executor.read_jsonl(Path(plan["files"]["fx_rate_raw"]["path"]))[0]
            row["rate"] = -1.0
            plan["files"]["fx_rate_raw"] = write_jsonl(root / "fx.jsonl", [row])
            plan = finalize_plan(plan)
            client_factory = Mock(side_effect=AssertionError("BigQuery client must not be called"))
            module = Mock(Client=client_factory)
            with self.assertRaisesRegex(executor.Wp04BackfillError, "fx_rate_raw"):
                executor.execute_plan(
                    plan=plan,
                    project_id="stocks-437902",
                    dataset_id="acciones_dataset_shadow_wp04_test",
                    location="us-east1",
                    bigquery_module=module,
                    bq_operations_module=Mock(),
                )
            client_factory.assert_not_called()

    def test_every_official_row_security_field_is_revalidated(self):
        observed = dt.datetime(2026, 8, 20, 12, tzinfo=UTC)
        row = source._raw_row(
            rate_date=dt.date(2024, 1, 3),
            source_reference_date=dt.date(2024, 1, 2),
            rate=900.0,
            ingestion_run_id="run",
            ingested_at=observed,
        )
        mutations = {
            "provider": "OTHER",
            "series_id": "OTHER",
            "base_currency": "EUR",
            "quote_currency": "USD",
            "status_code": "ND",
            "source_version": "other",
            "source_timezone": "UTC",
            "availability_policy": "retired",
            "quality_status": "OFFICIAL_PUBLISHED_RATE",
            "rate": float("inf"),
            "rate_date": "not-a-date",
            "source_reference_date": "2024-01-03",
            "source_published_at": "2024-01-02T00:00:00+00:00",
            "first_observed_at": "2026-08-19T12:00:00+00:00",
            "available_at": "2024-01-02T20:30:00+00:00",
            "ingested_at": "2026-08-21T12:00:00+00:00",
            "backtest_eligible": True,
            "production_change_allowed": True,
            "payload_hash": "0" * 64,
            "fx_rate_record_id": "bad",
            "fx_rate_revision_id": "bad",
            "source_record_id": "bad",
            "publication_evidence_uri": "gs://unverified/archive",
            "publication_evidence_sha256": "a" * 64,
            "publication_evidence_at": "2024-01-02T20:30:00+00:00",
            "ingestion_run_id": "",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(row)
                changed[field] = value
                with self.assertRaises(source.OfficialFxSourceError):
                    source.validate_official_fx_row(changed)
        missing = copy.deepcopy(row)
        del missing["payload_hash"]
        with self.assertRaises(source.OfficialFxSourceError):
            source.validate_official_fx_row(missing)
        changed = copy.deepcopy(row)
        changed["ingestion_run_id"] = "different-run"
        with self.assertRaises(source.OfficialFxSourceError):
            source.validate_official_fx_row(
                changed,
                expected_ingestion_run_id="run",
                expected_observed_at=observed,
            )

    def test_every_official_status_security_field_is_revalidated(self):
        observed = dt.datetime(2026, 8, 20, 12, tzinfo=UTC)
        status = source.build_status_document(
            query_start_date=dt.date(2023, 11, 30),
            start_date=dt.date(2024, 1, 1),
            end_date=dt.date(2024, 1, 3),
            ingestion_run_id="run",
            accepted_row_count=1,
            skipped_status_counts={},
            observed_at=observed,
        )
        mutations = {
            "status_id": "bad",
            "policy_version": "retired",
            "provider": "OTHER",
            "series_id": "OTHER",
            "required": False,
            "authentication_mode": "NONE",
            "accepted_row_count": 2,
            "source_version": "other",
            "availability_policy": "retired",
            "production_change_allowed": True,
            "query_start_date": "2024-02-01",
            "start_date": "2024-02-01",
            "end_date": "2023-12-31",
            "skipped_status_counts": {"ND": 1},
            "observed_at": "2026-08-20T12:00:00",
            "ingestion_run_id": "",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(status)
                changed[field] = value
                with self.assertRaises(source.OfficialFxSourceError):
                    source.validate_official_fx_status(changed, row_count=1)
        extra = copy.deepcopy(status)
        extra["unexpected"] = "field"
        with self.assertRaises(source.OfficialFxSourceError):
            source.validate_official_fx_status(extra, row_count=1)


if __name__ == "__main__":
    unittest.main()
