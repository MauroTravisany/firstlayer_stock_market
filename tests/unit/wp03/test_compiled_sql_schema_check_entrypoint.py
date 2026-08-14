import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
STABLE_ENTRYPOINT = ROOT / "tools" / "wp03_compiled_sql_schema_check.py"
IMPLEMENTATION = ROOT / "tools" / "wp03_compiled_sql_semantic_preflight.py"
HANDOFF = (
    ROOT
    / "docs"
    / "audit-grade"
    / "runbooks"
    / "WP-03_SCHEMA_CHECK_ENTRYPOINT.md"
)


def load_stable_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "wp03_compiled_sql_schema_check",
        STABLE_ENTRYPOINT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CompiledSqlSchemaCheckEntrypointTests(unittest.TestCase):
    def test_stable_entrypoint_exists_and_reexports_reviewed_implementation(self):
        self.assertTrue(STABLE_ENTRYPOINT.is_file())
        self.assertTrue(IMPLEMENTATION.is_file())
        module = load_stable_entrypoint()
        self.assertEqual(12, len(module.REQUIRED_OUTPUTS))
        self.assertEqual(
            "WP03_SCHEMA_VALIDATION_WRITE",
            module.ACKNOWLEDGEMENT,
        )
        self.assertIs(module.main, module._implementation.main)
        self.assertIs(module.build_plan, module._implementation.build_plan)
        self.assertIs(
            module.execute_schema_graph,
            module._implementation.execute_schema_graph,
        )

    def test_stable_entrypoint_executes_as_a_script(self):
        result = subprocess.run(
            [sys.executable, str(STABLE_ENTRYPOINT), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--actions-json", result.stdout)
        self.assertIn("--expected-git-sha", result.stdout)
        self.assertIn("--acknowledge-validation-write", result.stdout)

    def test_handoff_declares_the_stable_path_and_actual_success_status(self):
        text = HANDOFF.read_text(encoding="utf-8")
        self.assertIn("tools/wp03_compiled_sql_schema_check.py", text)
        self.assertIn("ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS", text)
        self.assertIn("production_change_allowed = false", text)
        self.assertIn("internal implementation", text)


if __name__ == "__main__":
    unittest.main()
