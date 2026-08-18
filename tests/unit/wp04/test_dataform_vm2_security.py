import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
DATAFORM = ROOT / "dataform"


class DataformVm2SecurityTests(unittest.TestCase):
    def test_dataform_resolves_patched_vm2(self):
        package = json.loads(
            (DATAFORM / "package.json").read_text(encoding="utf-8")
        )
        lock = json.loads(
            (DATAFORM / "package-lock.json").read_text(encoding="utf-8")
        )

        self.assertEqual("3.11.6", package["overrides"]["vm2"])

        vm2 = lock["packages"]["node_modules/vm2"]
        self.assertEqual("3.11.6", vm2["version"])
        self.assertEqual(
            "https://registry.npmjs.org/vm2/-/vm2-3.11.6.tgz",
            vm2["resolved"],
        )
        self.assertRegex(vm2["integrity"], r"^sha512-[A-Za-z0-9+/]+=*$")

    def test_temporary_lock_refresh_workflow_is_absent(self):
        self.assertFalse(
            (ROOT / ".github/workflows/wp04-lock-refresh.yml").exists()
        )


if __name__ == "__main__":
    unittest.main()
