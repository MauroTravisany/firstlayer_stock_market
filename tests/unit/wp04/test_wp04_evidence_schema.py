import unittest

from tools import wp04_shadow_evidence as evidence


class Wp04EvidenceSchemaTests(unittest.TestCase):
    def contract(self, mode):
        return {
            "columns": [
                {"name": "id", "type": "STRING", "mode": "REQUIRED"},
                {"name": "values", "type": "ARRAY<STRING>", "mode": "REPEATED"},
            ],
            "implementation": {
                "mode": mode,
                "allow_additional_columns": False,
            },
        }

    def test_ctas_scalar_required_may_be_observed_nullable(self):
        drift = evidence.compare_materialized_schema(
            self.contract("CODE_SCHEMA_REFERENCE"),
            [
                {"name": "id", "type": "STRING", "mode": "NULLABLE"},
                {"name": "values", "type": "STRING", "mode": "REPEATED"},
            ],
        )
        self.assertEqual([], drift)

    def test_repeated_mode_and_types_remain_strict(self):
        drift = evidence.compare_materialized_schema(
            self.contract("CODE_SCHEMA_REFERENCE"),
            [
                {"name": "id", "type": "INT64", "mode": "NULLABLE"},
                {"name": "values", "type": "STRING", "mode": "NULLABLE"},
            ],
        )
        self.assertIn("COLUMN_TYPE:id:expected=STRING:actual=INT64", drift)
        self.assertIn("COLUMN_MODE:values:expected=REPEATED:actual=NULLABLE", drift)

    def test_explicit_contract_tables_remain_mode_strict(self):
        drift = evidence.compare_materialized_schema(
            self.contract("DATAFORM_CREATE"),
            [
                {"name": "id", "type": "STRING", "mode": "NULLABLE"},
                {"name": "values", "type": "STRING", "mode": "REPEATED"},
            ],
        )
        self.assertIn(
            "COLUMN_SHAPE:id:expected=STRING/REQUIRED:actual=STRING/NULLABLE",
            drift,
        )


if __name__ == "__main__":
    unittest.main()
