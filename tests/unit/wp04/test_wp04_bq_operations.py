import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
PATH = (
    ROOT
    / "cloud-functions"
    / "daily_stocks"
    / "custom_function"
    / "wp04_bq_operations.py"
)
SOURCE = PATH.read_text(encoding="utf-8")


class Wp04BigQueryOperationsTests(unittest.TestCase):
    def test_module_is_syntactically_valid(self):
        ast.parse(SOURCE)

    def test_merge_is_insert_only(self):
        upper = SOURCE.upper()
        self.assertIn("WHEN NOT MATCHED THEN", upper)
        self.assertNotIn("WHEN MATCHED THEN", upper)
        self.assertNotIn("UPDATE SET", upper)
        self.assertNotIn("DELETE FROM", upper)

    def test_writer_requires_shadow_labels_and_exact_schema(self):
        self.assertIn('labels.get("environment") != "shadow"', SOURCE)
        self.assertIn('labels.get("work_package") != "wp04"', SOURCE)
        self.assertIn("destination schema does not match", SOURCE)

    def test_production_change_is_never_allowed(self):
        self.assertIn('"production_change_allowed": False', SOURCE)


if __name__ == "__main__":
    unittest.main()
