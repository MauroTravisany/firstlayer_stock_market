from pathlib import Path
import types
import unittest
from unittest import mock

from tools import wp03_shadow_preflight as preflight


ROOT = Path(__file__).resolve().parents[3]


class FakeField:
    def __init__(self, name, field_type="STRING", mode="NULLABLE"):
        self.name = name
        self.field_type = field_type
        self.mode = mode


class FakeTable:
    def __init__(
        self,
        table_id,
        columns,
        *,
        table_type="TABLE",
        num_rows=1,
    ):
        self.table_id = table_id
        self.table_type = table_type
        self.num_rows = num_rows
        self.modified = None
        self.schema = [FakeField(column) for column in columns]


class FakeDataset:
    def __init__(self, dataset_id, *, location="us-east1", labels=None):
        self.dataset_id = dataset_id
        self.location = location
        self.labels = labels or {}


class FakeClient:
    def __init__(
        self,
        *,
        project_id="stocks-437902",
        operational_dataset="acciones_dataset",
        shadow_dataset="acciones_dataset_shadow_wp03",
        missing_tables=(),
        column_overrides=None,
        shadow_tables=(),
    ):
        self.project_id = project_id
        self.operational_dataset = operational_dataset
        self.shadow_dataset = shadow_dataset
        self.missing_tables = set(missing_tables)
        self.column_overrides = column_overrides or {}
        self.shadow_tables = tuple(shadow_tables)

    def get_dataset(self, dataset_id):
        if dataset_id == f"{self.project_id}.{self.operational_dataset}":
            return FakeDataset(dataset_id)
        if dataset_id == f"{self.project_id}.{self.shadow_dataset}":
            return FakeDataset(
                dataset_id,
                labels={
                    "environment": "shadow",
                    "work_package": "wp03",
                },
            )
        raise RuntimeError(f"missing dataset {dataset_id}")

    def get_table(self, table_id):
        table_name = table_id.rsplit(".", 1)[-1]
        if table_name in self.missing_tables:
            raise RuntimeError(f"missing table {table_name}")
        contract = preflight.OPERATIONAL_INPUTS[table_name]
        columns = self.column_overrides.get(
            table_name,
            contract["required_columns"],
        )
        return FakeTable(table_id, columns)

    def list_tables(self, _dataset_id):
        return [
            types.SimpleNamespace(table_id=table_id)
            for table_id in self.shadow_tables
        ]


class Wp03ShadowPreflightTests(unittest.TestCase):
    def test_dependency_manifest_covers_every_external_live_input(self):
        self.assertEqual(
            {
                "macro_earnings_calendar",
                "trading_price_features",
                "asset_profile",
                "valuation_model_profile",
                "trading_historical_context",
                "portfolio_valuation_daily",
            },
            set(preflight.OPERATIONAL_INPUTS),
        )
        self.assertNotIn(
            "legacy_result_registry",
            preflight.OPERATIONAL_INPUTS,
        )
        for name, contract in preflight.OPERATIONAL_INPUTS.items():
            with self.subTest(name=name):
                self.assertTrue(contract["consumers"])
                self.assertTrue(contract["required_columns"])

    def test_scope_rejects_operational_shadow_aliasing(self):
        with self.assertRaisesRegex(
            preflight.PreflightError,
            "must be different",
        ):
            preflight.validate_scope(
                "stocks-437902",
                "acciones_dataset",
                "acciones_dataset",
                "us-east1",
            )
        with self.assertRaisesRegex(
            preflight.PreflightError,
            "contain 'shadow'",
        ):
            preflight.validate_scope(
                "stocks-437902",
                "acciones_dataset",
                "wp03_validation",
                "us-east1",
            )

    def test_preflight_passes_when_every_dependency_is_present(self):
        client = FakeClient()
        with mock.patch.object(
            preflight,
            "inspect_repository_static_registry",
            return_value={
                "status": "PASS",
                "resolution_mode": "FROZEN_REPOSITORY_SNAPSHOT",
                "problems": [],
            },
        ):
            result = preflight.run_preflight(
                client=client,
                project_id="stocks-437902",
                operational_dataset="acciones_dataset",
                shadow_dataset="acciones_dataset_shadow_wp03",
                location="us-east1",
                git_sha="a" * 40,
            )
        self.assertEqual("PASS", result["status"])
        self.assertEqual([], result["problems"])
        self.assertFalse(result["production_change_allowed"])
        self.assertRegex(
            result["preflight_checksum"],
            r"^[0-9a-f]{64}$",
        )
        self.assertTrue(
            all(
                item["status"] == "PASS"
                for item in result["operational_inputs"].values()
            )
        )

    def test_preflight_reports_all_missing_or_incompatible_inputs(self):
        trading_columns = list(
            preflight.OPERATIONAL_INPUTS[
                "trading_price_features"
            ]["required_columns"]
        )
        trading_columns.remove("previous_close")
        client = FakeClient(
            missing_tables=(
                "macro_earnings_calendar",
                "portfolio_valuation_daily",
            ),
            column_overrides={
                "trading_price_features": trading_columns,
            },
        )
        with mock.patch.object(
            preflight,
            "inspect_repository_static_registry",
            return_value={
                "status": "PASS",
                "resolution_mode": "FROZEN_REPOSITORY_SNAPSHOT",
                "problems": [],
            },
        ):
            result = preflight.run_preflight(
                client=client,
                project_id="stocks-437902",
                operational_dataset="acciones_dataset",
                shadow_dataset="acciones_dataset_shadow_wp03",
                location="us-east1",
                git_sha="a" * 40,
            )
        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "OPERATIONAL_INPUT_INVALID:macro_earnings_calendar",
            result["problems"],
        )
        self.assertIn(
            "OPERATIONAL_INPUT_INVALID:portfolio_valuation_daily",
            result["problems"],
        )
        self.assertIn(
            "OPERATIONAL_INPUT_INVALID:trading_price_features",
            result["problems"],
        )
        self.assertEqual(
            ["previous_close"],
            result["operational_inputs"][
                "trading_price_features"
            ]["missing_columns"],
        )

    def test_unknown_shadow_tables_fail_closed(self):
        client = FakeClient(shadow_tables=("unrelated_live_copy",))
        with mock.patch.object(
            preflight,
            "inspect_repository_static_registry",
            return_value={
                "status": "PASS",
                "resolution_mode": "FROZEN_REPOSITORY_SNAPSHOT",
                "problems": [],
            },
        ):
            result = preflight.run_preflight(
                client=client,
                project_id="stocks-437902",
                operational_dataset="acciones_dataset",
                shadow_dataset="acciones_dataset_shadow_wp03",
                location="us-east1",
                git_sha="a" * 40,
            )
        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "unrelated_live_copy",
            result["datasets"]["shadow"]["unexpected_tables"],
        )

    def test_frozen_legacy_registry_is_self_contained_and_in_sync(self):
        result = preflight.inspect_repository_static_registry(ROOT)
        self.assertEqual("PASS", result["status"], result["problems"])
        self.assertEqual(
            "FROZEN_REPOSITORY_SNAPSHOT",
            result["resolution_mode"],
        )
        self.assertEqual(
            len(preflight.FROZEN_AFFECTED_RESULTS),
            result["affected_result_count"],
        )

    def test_tool_has_no_bigquery_mutation_surface(self):
        source = (
            ROOT / "tools" / "wp03_shadow_preflight.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in (
            "client.query(",
            "create_dataset(",
            "update_dataset(",
            "delete_dataset(",
            "create_table(",
            "update_table(",
            "delete_table(",
            "load_table",
            "insert_rows",
            "terraform apply",
            "gcloud run deploy",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
