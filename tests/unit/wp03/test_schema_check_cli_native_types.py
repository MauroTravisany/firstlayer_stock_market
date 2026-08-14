import unittest
from unittest import mock

from tools import wp03_compiled_sql_semantic_preflight as preflight


class SchemaCheckCliNativeTypeTests(unittest.TestCase):
    def test_cli_installs_strict_native_type_planner_and_restores_core(self):
        original = preflight._core.build_plan

        def observe_core_main():
            self.assertIs(
                preflight.build_plan_strict,
                preflight._core.build_plan,
            )
            return 0

        with mock.patch.object(
            preflight,
            "_CORE_MAIN",
            side_effect=observe_core_main,
        ):
            self.assertEqual(0, preflight.main())

        self.assertIs(original, preflight._core.build_plan)


if __name__ == "__main__":
    unittest.main()
