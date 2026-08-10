import datetime as dt
import unittest

from scripts.ci import npm_audit_gate


def audit(package="vm2", advisory="GHSA-test-0000-0000"):
    return {
        "vulnerabilities": {
            package: {
                "name": package,
                "severity": "critical",
                "via": [
                    {
                        "source": 1,
                        "name": package,
                        "severity": "critical",
                        "url": f"https://github.com/advisories/{advisory}",
                    }
                ],
            }
        }
    }


def lock(package="vm2", version="3.9.19"):
    return {"packages": {f"node_modules/{package}": {"version": version}}}


def allowlist(**overrides):
    row = {
        "advisory": "GHSA-test-0000-0000",
        "package": "vm2",
        "version": "3.9.19",
        "surface": "dataform",
        "reason": "Inherited toolchain dependency",
        "owner": "@MauroTravisany",
        "remediation_issue": "https://github.com/MauroTravisany/firstlayer_stock_market/issues/36",
        "expires_on": "2026-09-30",
    }
    row.update(overrides)
    return {"version": 1, "exceptions": [row]}


class NpmAuditGateTests(unittest.TestCase):
    def test_exact_unexpired_exception_is_accepted(self):
        result = npm_audit_gate.evaluate_audit(
            audit(), lock(), allowlist(), "dataform", dt.date(2026, 8, 10)
        )
        self.assertEqual(result["status"], "PASS")

    def test_unlisted_critical_vulnerability_fails(self):
        with self.assertRaises(npm_audit_gate.NpmAuditError):
            npm_audit_gate.evaluate_audit(
                audit(advisory="GHSA-new0-0000-0000"),
                lock(),
                allowlist(),
                "dataform",
                dt.date(2026, 8, 10),
            )

    def test_missing_or_expired_expiry_fails(self):
        for expires_on in (None, "2026-08-09"):
            with self.subTest(expires_on=expires_on):
                with self.assertRaises(npm_audit_gate.NpmAuditError):
                    npm_audit_gate.evaluate_audit(
                        audit(),
                        lock(),
                        allowlist(expires_on=expires_on),
                        "dataform",
                        dt.date(2026, 8, 10),
                    )

    def test_package_or_version_change_fails(self):
        for package_lock in (lock("vm-two"), lock(version="3.9.20")):
            with self.subTest(lock=package_lock):
                with self.assertRaises(npm_audit_gate.NpmAuditError):
                    npm_audit_gate.evaluate_audit(
                        audit(), package_lock, allowlist(), "dataform", dt.date(2026, 8, 10)
                    )


if __name__ == "__main__":
    unittest.main()
