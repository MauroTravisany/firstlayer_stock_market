import unittest

from scripts.ci import verify_main_sha


SHA_A = "a" * 40
SHA_B = "b" * 40


class VerifyMainShaTests(unittest.TestCase):
    def verify(self, **overrides):
        values = {
            "event_name": "workflow_run",
            "conclusion": "success",
            "workflow_event": "push",
            "head_branch": "main",
            "head_repository": "owner/repository",
            "repository": "owner/repository",
            "head_sha": SHA_A,
            "current_main_sha": SHA_A,
        }
        values.update(overrides)
        return verify_main_sha.validate_workflow_source(**values)

    def test_current_main_sha_is_accepted(self):
        self.assertEqual(self.verify(), SHA_A)

    def test_stale_sha_is_rejected(self):
        with self.assertRaises(verify_main_sha.SourceVerificationError):
            self.verify(current_main_sha=SHA_B)

    def test_foreign_repository_is_rejected(self):
        with self.assertRaises(verify_main_sha.SourceVerificationError):
            self.verify(head_repository="attacker/fork")

    def test_failed_ci_is_rejected(self):
        with self.assertRaises(verify_main_sha.SourceVerificationError):
            self.verify(conclusion="failure")

    def test_non_push_ci_event_is_rejected(self):
        with self.assertRaises(verify_main_sha.SourceVerificationError):
            self.verify(workflow_event="pull_request")


if __name__ == "__main__":
    unittest.main()
