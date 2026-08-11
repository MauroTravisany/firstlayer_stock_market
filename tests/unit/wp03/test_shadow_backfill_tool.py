import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools" / "wp03_shadow_backfill.py"
spec = importlib.util.spec_from_file_location("wp03_shadow_backfill", MODULE_PATH)
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)


class _Field:
    def __init__(self, name, field_type="STRING", mode="NULLABLE"):
        self.name = name
        self.field_type = field_type
        self.mode = mode


class _PitOps:
    PIT_STATEMENTS_SCHEMA = [_Field("revision_id", "STRING", "REQUIRED")]

    @staticmethod
    def _validated_table_id(value):
        return value


class _Dataset:
    def __init__(self, labels):
        self.labels = labels


class _Table:
    schema = _PitOps.PIT_STATEMENTS_SCHEMA


class _Client:
    labels = {}

    def __init__(self, **_kwargs):
        pass

    def get_dataset(self, _dataset_id):
        return _Dataset(self.labels)

    def get_table(self, _table_id):
        return _Table()


class _BigQuery:
    Client = _Client


class ShadowBackfillToolTests(unittest.TestCase):
    def test_tickers_are_explicit_unique_and_bounded(self):
        self.assertEqual(["AAPL", "MSFT"], backfill.parse_tickers("aapl, msft"))
        with self.assertRaisesRegex(ValueError, "duplicates"):
            backfill.parse_tickers("AAPL,aapl")
        with self.assertRaisesRegex(ValueError, "At most"):
            backfill.parse_tickers(",".join(f"T{index}" for index in range(11)))

    def test_fiscal_year_range_is_bounded(self):
        backfill._validate_year_range(2017, 2026)
        with self.assertRaisesRegex(ValueError, "after"):
            backfill._validate_year_range(2026, 2025)
        with self.assertRaisesRegex(ValueError, "at most"):
            backfill._validate_year_range(2016, 2026)

    def test_dataset_name_must_be_isolated_shadow(self):
        self.assertEqual(
            "acciones_dataset_shadow_wp03",
            backfill._validated_shadow_dataset_id("acciones_dataset_shadow_wp03"),
        )
        with self.assertRaisesRegex(ValueError, "contains 'shadow'"):
            backfill._validated_shadow_dataset_id("acciones_dataset")

    def test_checkout_must_match_exact_sha_and_be_clean(self):
        expected = "a" * 40
        with mock.patch.object(backfill, "_git_sha", return_value=expected), mock.patch.object(
            backfill, "_run_git", return_value=""
        ):
            self.assertEqual(expected, backfill.verify_clean_checkout(expected))
        with mock.patch.object(backfill, "_git_sha", return_value="b" * 40):
            with self.assertRaisesRegex(RuntimeError, "SHA mismatch"):
                backfill.verify_clean_checkout(expected)
        with mock.patch.object(backfill, "_git_sha", return_value=expected), mock.patch.object(
            backfill, "_run_git", return_value=" M modified.py"
        ):
            with self.assertRaisesRegex(RuntimeError, "clean checkout"):
                backfill.verify_clean_checkout(expected)

    def test_execute_rejects_unlabeled_or_wrongly_labeled_dataset(self):
        with mock.patch.object(
            backfill, "_load_bigquery_modules", return_value=(_BigQuery, _PitOps)
        ):
            _Client.labels = {"environment": "shadow"}
            with self.assertRaisesRegex(RuntimeError, "work_package=wp03"):
                backfill.execute_shadow_write(
                    rows=[],
                    project_id="project",
                    dataset_id="dataset_shadow_wp03",
                    table_id="financial_statements_pit_raw",
                    location="us-east1",
                )
            _Client.labels = {"environment": "shadow", "work_package": "wp03"}
            result = backfill.execute_shadow_write(
                rows=[],
                project_id="project",
                dataset_id="dataset_shadow_wp03",
                table_id="financial_statements_pit_raw",
                location="us-east1",
            )
        self.assertEqual(0, result["inserted_rows"])
        self.assertEqual("shadow", result["dataset_labels"]["environment"])


if __name__ == "__main__":
    unittest.main()
