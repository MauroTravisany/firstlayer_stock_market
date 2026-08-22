import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import wp04_official_fx_planner as planner
from tools import wp04_shadow_backfill_official_fx as executor
from tools import wp04_shadow_backfill_windowed_official_fx as windowed
from tools.wp04_backfill_core import finalize_plan, read_jsonl, write_jsonl
from tools.wp04_fx_source import (
    AVAILABILITY_POLICY,
    POLICY_VERSION,
    SOURCE_VERSION,
    _raw_row,
    build_status_document,
    official_source_policy,
)


ROOT = Path(__file__).resolve().parents[3]
ASSET_SET = ROOT / "config" / "wp04_shadow_assets.v1.json"
UTC = dt.timezone.utc


class Wp04OfficialFxPlannerTests(unittest.TestCase):
    def test_plan_separates_market_bars_from_official_scalar_fx(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            captured = {}
            timeline = []
            plan_started_at = dt.datetime(2026, 8, 20, 12, tzinfo=UTC)
            market_finished_at = dt.datetime(2026, 8, 20, 12, 1, tzinfo=UTC)
            fx_observed_at = dt.datetime(2026, 8, 20, 12, 2, tzinfo=UTC)

            def market_planner(**kwargs):
                timeline.append(("market_started", plan_started_at))
                captured.update(kwargs)
                files = {
                    "market_price_raw": write_jsonl(work / "market_price_raw.jsonl", []),
                    "corporate_actions_pit": write_jsonl(work / "corporate_actions_pit.jsonl", []),
                    "market_session_calendar": write_jsonl(work / "market_session_calendar.jsonl", []),
                    "secondary_source_status": write_jsonl(work / "secondary_source_status.jsonl", []),
                    "fx_reference_status": write_jsonl(work / "fx_reference_status.jsonl", []),
                    "primary_source_status": write_jsonl(work / "primary_source_status.jsonl", []),
                    "primary_source_rejections": write_jsonl(work / "primary_source_rejections.jsonl", []),
                }
                result = finalize_plan(
                    {
                        "schema_version": 1,
                        "operation": "WP04_SHADOW_BACKFILL",
                        "mode": "PLAN",
                        "git_sha": kwargs["git_sha"],
                        "asset_set_version": "placeholder",
                        "asset_set_sha256": "a" * 64,
                        "assets": [],
                        "asset_results": [],
                        "start_date": kwargs["start_date"].isoformat(),
                        "end_date": kwargs["end_date"].isoformat(),
                        "intraday_start_date": kwargs["intraday_start_date"].isoformat(),
                        "hourly_start_date": kwargs["hourly_start_date"].isoformat(),
                        "files": files,
                        "total_row_count": 0,
                        "max_rows": kwargs["max_rows"],
                        "provider_versions": {"YAHOO": "test", "FX_REFERENCE_POLICY": "retired"},
                        "ingestion_run_id": "run-test",
                        "generated_at": plan_started_at.isoformat(),
                        "fx_reference_policy": {"retired": True},
                        "primary_source_policy": {"policy_version": "test"},
                        "secondary_source_required": False,
                        "secondary_source_available_count": 0,
                        "secondary_source_unavailable_count": 5,
                        "production_change_allowed": False,
                    }
                )
                timeline.append(("market_finished", market_finished_at))
                return result

            def fx_clock():
                self.assertEqual("market_finished", timeline[-1][0])
                timeline.append(("fx_observed", fx_observed_at))
                return fx_observed_at

            def fx_fetcher(**kwargs):
                self.assertNotIn("ingested_at", kwargs)
                observed_at = kwargs["clock"]()
                row = _raw_row(
                    rate_date=dt.date(2024, 1, 3),
                    source_reference_date=dt.date(2024, 1, 2),
                    rate=900.0,
                    ingestion_run_id=kwargs["ingestion_run_id"],
                    ingested_at=observed_at,
                )
                status = build_status_document(
                    query_start_date=dt.date(2023, 11, 30),
                    start_date=kwargs["start_date"],
                    end_date=kwargs["end_date"],
                    ingestion_run_id=kwargs["ingestion_run_id"],
                    accepted_row_count=1,
                    skipped_status_counts={},
                    observed_at=observed_at,
                )
                return [row], status

            plan = planner.build_plan(
                git_sha="a" * 40,
                asset_set_path=ASSET_SET,
                tickers=None,
                start_date=dt.date(2024, 1, 1),
                end_date=dt.date(2024, 1, 5),
                intraday_start_date=dt.date(2024, 1, 1),
                hourly_start_date=dt.date(2024, 1, 1),
                max_rows=10_000,
                work_dir=work,
                timeout_seconds=5,
                market_planner=market_planner,
                fx_fetcher=fx_fetcher,
                fx_clock=fx_clock,
                bcch_api_token="private-token",
            )
            self.assertNotIn("CLP=X", captured["tickers"].split(","))
            self.assertEqual(
                {"AAPL", "MSFT", "NVDA", "META", "AMZN", "BTC-USD", "ETH-USD"},
                set(captured["tickers"].split(",")),
            )
            self.assertEqual(12, 5 * 2 + 2)
            self.assertFalse(captured["require_secondary_source"])
            self.assertIsNone(captured["bcch_api_token"])
            self.assertEqual(8, len(plan["assets"]))
            self.assertEqual("DIAGNOSTIC_ONLY", plan["assets"][-1]["yahoo_role"])
            self.assertIn("fx_rate_raw", plan["files"])
            self.assertIn("official_fx_source_status", plan["files"])
            self.assertNotIn("fx_reference_status", plan["files"])
            self.assertNotIn("fx_reference_policy", plan)
            self.assertEqual(POLICY_VERSION, plan["provider_versions"]["OFFICIAL_FX_POLICY"])
            self.assertFalse(plan["production_change_allowed"])
            self.assertNotIn("private-token", json.dumps(plan, default=str))
            fx_rows = read_jsonl(Path(plan["files"]["fx_rate_raw"]["path"]))
            status_rows = read_jsonl(
                Path(plan["files"]["official_fx_source_status"]["path"])
            )
            self.assertEqual(plan_started_at.isoformat(), plan["generated_at"])
            serialized_observed_at = fx_observed_at.isoformat().replace("+00:00", "Z")
            for field in ("first_observed_at", "available_at", "ingested_at"):
                self.assertEqual(serialized_observed_at, fx_rows[0][field])
            self.assertEqual(serialized_observed_at, status_rows[0]["observed_at"])
            self.assertNotEqual(plan["generated_at"], fx_rows[0]["first_observed_at"])
            self.assertEqual(
                [
                    ("market_started", plan_started_at),
                    ("market_finished", market_finished_at),
                    ("fx_observed", fx_observed_at),
                ],
                timeline,
            )
            before = plan["plan_checksum"]
            changed = dict(plan)
            changed["official_fx_source_policy"] = {
                **plan["official_fx_source_policy"],
                "series_id": "wrong",
            }
            self.assertNotEqual(before, finalize_plan(changed)["plan_checksum"])

    def test_windowed_entrypoint_uses_one_anchor_and_official_planner(self):
        captured = {}

        def fake_planner(**kwargs):
            captured.update(kwargs)
            return {
                "schema_version": 1,
                "operation": "WP04_SHADOW_BACKFILL",
                "git_sha": kwargs["git_sha"],
                "asset_set_version": "v2",
                "asset_set_sha256": "b" * 64,
                "assets": [],
                "asset_results": [],
                "start_date": kwargs["start_date"].isoformat(),
                "end_date": kwargs["end_date"].isoformat(),
                "intraday_start_date": kwargs["intraday_start_date"].isoformat(),
                "hourly_start_date": kwargs["hourly_start_date"].isoformat(),
                "files": {},
                "total_row_count": 0,
                "max_rows": kwargs["max_rows"],
                "provider_versions": {},
                "ingestion_run_id": "run",
                "generated_at": "2026-08-20T12:00:00+00:00",
                "official_fx_source_policy": {},
                "production_change_allowed": False,
            }

        plan, window = windowed.build_windowed_plan(
            git_sha="a" * 40,
            asset_set_path=ASSET_SET,
            tickers=None,
            daily_start_date=dt.date(2024, 1, 1),
            end_lag_days=2,
            intraday_lookback_days=45,
            hourly_lookback_days=365,
            max_rows=100_000,
            work_dir=Path("/tmp/test"),
            timeout_seconds=5,
            bcch_api_token="private-token",
            anchor_at=dt.datetime(2026, 8, 20, 12, tzinfo=UTC),
            planner=fake_planner,
        )
        self.assertEqual(window["window_checksum"], plan["provider_window_checksum"])
        self.assertEqual("private-token", captured["bcch_api_token"])
        self.assertNotIn("private-token", json.dumps(plan, default=str))


class Wp04OfficialFxExecutorTests(unittest.TestCase):
    def plan(self, root):
        files = {
            "market_price_raw": write_jsonl(root / "market.jsonl", []),
            "corporate_actions_pit": write_jsonl(root / "actions.jsonl", []),
            "market_session_calendar": write_jsonl(root / "calendar.jsonl", []),
            "fx_rate_raw": write_jsonl(
                root / "fx.jsonl",
                [
                    _raw_row(
                        rate_date=dt.date(2024, 1, 3),
                        source_reference_date=dt.date(2024, 1, 2),
                        rate=900.0,
                        ingestion_run_id="run",
                        ingested_at=dt.datetime(2024, 1, 4, tzinfo=UTC),
                    )
                ],
            ),
            "official_fx_source_status": write_jsonl(
                root / "status.jsonl",
                [
                    build_status_document(
                        query_start_date=dt.date(2023, 11, 30),
                        start_date=dt.date(2024, 1, 1),
                        end_date=dt.date(2024, 1, 3),
                        ingestion_run_id="run",
                        accepted_row_count=1,
                        skipped_status_counts={},
                        observed_at=dt.datetime(2024, 1, 4, tzinfo=UTC),
                    )
                ],
            ),
        }
        return {
            "files": files,
            "provider_versions": {
                "BCCH_BDE": SOURCE_VERSION,
                "OFFICIAL_FX_POLICY": POLICY_VERSION,
                "OFFICIAL_FX_AVAILABILITY_POLICY": AVAILABILITY_POLICY,
            },
            "official_fx_source_policy": official_source_policy(),
        }

    def test_official_plan_requires_four_executable_files_and_rejects_fx_bars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan(root)
            executor.verify_official_plan(plan)
            self.assertEqual(4, len(executor.EXECUTABLE_TABLES))
            bad = dict(plan)
            bad["official_fx_source_policy"] = {}
            with self.assertRaisesRegex(executor.Wp04BackfillError, "official_fx_source_policy"):
                executor.verify_official_plan(bad)

    def test_executor_rejects_non_shadow_and_invalid_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(Path(directory))
            with self.assertRaisesRegex(executor.Wp04BackfillError, "contain shadow"):
                executor.execute_plan(
                    plan=plan,
                    project_id="stocks-437902",
                    dataset_id="acciones_dataset",
                    location="us-east1",
                )
            client = SimpleNamespace(
                get_dataset=lambda _name: SimpleNamespace(
                    labels={"environment": "shadow"},
                    location="us-east1",
                )
            )
            module = SimpleNamespace(SchemaField=lambda *args, **kwargs: (args, kwargs))
            operations = SimpleNamespace(PRICE_SCHEMA=(), ACTION_SCHEMA=())
            with patch.object(executor, "verify_plan_files"), self.assertRaisesRegex(
                executor.Wp04BackfillError, "dataset labels"
            ):
                executor.execute_plan(
                    plan=plan,
                    project_id="stocks-437902",
                    dataset_id="acciones_dataset_shadow_wp04_test",
                    location="us-east1",
                    client=client,
                    bigquery_module=module,
                    bq_operations_module=operations,
                )

    def test_executor_writes_exactly_four_tables_and_supports_zero_insert_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(Path(directory))
            client = SimpleNamespace(
                get_dataset=lambda _name: SimpleNamespace(
                    labels={"environment": "shadow", "work_package": "wp04"},
                    location="us-east1",
                )
            )
            module = SimpleNamespace(SchemaField=lambda *args, **kwargs: (args, kwargs))
            operations = SimpleNamespace(PRICE_SCHEMA=(), ACTION_SCHEMA=())
            destinations = []

            def append_rows(**kwargs):
                destinations.append(kwargs["destination"])
                return {
                    "destination_table": kwargs["destination"],
                    "staged_rows": len(kwargs["rows"]),
                    "inserted_rows": 0,
                }

            with patch.object(executor, "verify_plan_files"), patch.object(
                executor.base, "_append_rows", side_effect=append_rows
            ):
                result = executor.execute_plan(
                    plan=plan,
                    project_id="stocks-437902",
                    dataset_id="acciones_dataset_shadow_wp04_test",
                    location="us-east1",
                    client=client,
                    bigquery_module=module,
                    bq_operations_module=operations,
                )
            self.assertEqual(4, len(destinations))
            self.assertEqual(set(executor.EXECUTABLE_TABLES), set(result["writes"]))
            self.assertTrue(
                all(row["inserted_rows"] == 0 for row in result["writes"].values())
            )

    def test_executor_source_has_no_planning_deploy_or_broker_surface(self):
        source = (ROOT / "tools" / "wp04_shadow_backfill_official_fx.py").read_text(
            encoding="utf-8"
        ).lower()
        for forbidden in (
            "yfinance",
            "requests.get",
            "gcloud run deploy",
            "terraform apply",
            "submit_order",
            "alpaca",
            "when matched",
            "update ",
            "delete ",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("fx_rate_revision_id", source)
        self.assertIn("official_fx_source_policy", source)


if __name__ == "__main__":
    unittest.main()
