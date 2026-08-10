import unittest

from scripts.ci import verify_dataform_compatibility


def contract(columns=("ticker", "analysis_date"), phase="expand"):
    return {
        "schema_version": 1,
        "release_id": "candidate-v1",
        "phase": phase,
        "destructive_changes": [],
        "expanded_schema": {"acciones_dataset.signal": list(columns)},
        "consumer_contracts": {
            "legacy": {"acciones_dataset.signal": ["ticker"]},
            "current": {"acciones_dataset.signal": list(columns)},
        },
    }


class DataformCompatibilityTests(unittest.TestCase):
    def test_additive_expand_supports_old_and_new_consumers(self):
        result = verify_dataform_compatibility.validate_transition(
            contract(("ticker",)), contract()
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["phase"], "expand")

    def test_removed_legacy_column_fails(self):
        current = contract(("analysis_date",))
        with self.assertRaises(verify_dataform_compatibility.CompatibilityError):
            verify_dataform_compatibility.validate_transition(contract(), current)

    def test_missing_legacy_consumer_contract_fails(self):
        current = contract()
        del current["consumer_contracts"]["legacy"]
        with self.assertRaises(verify_dataform_compatibility.CompatibilityError):
            verify_dataform_compatibility.validate_transition(contract(), current)

    def test_contract_or_destructive_change_is_rejected_in_expand_release(self):
        current = contract(phase="contract")
        current["destructive_changes"] = ["drop ticker"]
        with self.assertRaises(verify_dataform_compatibility.CompatibilityError):
            verify_dataform_compatibility.validate_transition(contract(), current)

    def test_destructive_sql_is_rejected(self):
        for sql in (
            "ALTER TABLE x DROP COLUMN ticker",
            "DROP TABLE x",
            "ALTER TABLE x RENAME COLUMN a TO b",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(
                    verify_dataform_compatibility.CompatibilityError
                ):
                    verify_dataform_compatibility.reject_destructive_sql(sql)


if __name__ == "__main__":
    unittest.main()
