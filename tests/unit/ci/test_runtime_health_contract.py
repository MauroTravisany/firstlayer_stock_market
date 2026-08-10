import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
CONTEXTS = (
    ("daily_stocks", "stockdaily"),
    ("financial_data", "stockfinancial"),
    ("macro_data", "stockmacrodata"),
    ("daily_ai_analysis", "stockaianalysis"),
    ("paper_trading_alerts", "papertradingalerts"),
    ("paper_trade_executor", "papertradeexecutor"),
    ("paper_trade_risk_monitor", "papertraderiskmonitor"),
    ("strategy_brain", "strategybrain"),
)


class Request:
    def __init__(self, path, method="GET"):
        self.path = path
        self.method = method


def load_runtime(context):
    path = ROOT / "cloud-functions" / context / "runtime_health.py"
    spec = importlib.util.spec_from_file_location(f"runtime_health_{context}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeHealthContractTests(unittest.TestCase):
    def test_every_service_has_non_mutating_health_and_readiness(self):
        environment = {
            "RELEASE_GIT_SHA": "a" * 40,
            "RELEASE_VERSION": "release-a",
            "RELEASE_IMAGE_DIGEST": "sha256:" + "b" * 64,
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            for context, service in CONTEXTS:
                module = load_runtime(context)
                for path in ("/healthz", "/readyz"):
                    with self.subTest(context=context, path=path):
                        body, status, headers = module.health_response(
                            Request(path), service
                        )
                        payload = json.loads(body)
                        self.assertEqual(status, 200)
                        self.assertEqual(headers["Cache-Control"], "no-store")
                        self.assertEqual(payload["service"], service)
                        self.assertEqual(payload["operation"], "readiness_probe")
                        self.assertFalse(payload["mutation_performed"])

    def test_health_post_is_rejected_without_mutation(self):
        module = load_runtime("daily_stocks")
        body, status, _ = module.health_response(Request("/healthz", "POST"), "stockdaily")
        self.assertEqual(status, 405)
        self.assertFalse(json.loads(body)["mutation_performed"])

    def test_business_path_is_not_intercepted(self):
        module = load_runtime("daily_stocks")
        self.assertIsNone(module.health_response(Request("/"), "stockdaily"))


if __name__ == "__main__":
    unittest.main()
