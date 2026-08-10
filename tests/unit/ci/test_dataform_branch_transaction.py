import unittest

from scripts.ci import dataform_branch_transaction


OLD_SHA = "a" * 40
CANDIDATE_SHA = "b" * 40
OTHER_SHA = "c" * 40
PRODUCTION_REF = "refs/heads/dataform-production"
CANDIDATE_REF = "refs/heads/dataform-candidate-test"


class FakeRemote:
    def __init__(self):
        self.refs = {PRODUCTION_REF: OLD_SHA}
        self.operations = []

    def read(self, ref):
        return self.refs.get(ref)

    def compare_and_swap(self, ref, new_sha, expected_sha):
        self.operations.append((ref, new_sha, expected_sha))
        if self.refs.get(ref) != expected_sha:
            raise dataform_branch_transaction.DataformBranchError(
                "remote ref changed concurrently"
            )
        self.refs[ref] = new_sha


class DataformBranchTransactionTests(unittest.TestCase):
    def test_candidate_creation_never_moves_production(self):
        remote = FakeRemote()
        dataform_branch_transaction.create_candidate(
            CANDIDATE_REF, CANDIDATE_SHA, remote.read, remote.compare_and_swap
        )
        self.assertEqual(remote.read(PRODUCTION_REF), OLD_SHA)
        self.assertEqual(remote.read(CANDIDATE_REF), CANDIDATE_SHA)

    def test_compilation_failure_leaves_production_untouched(self):
        remote = FakeRemote()
        dataform_branch_transaction.create_candidate(
            CANDIDATE_REF, CANDIDATE_SHA, remote.read, remote.compare_and_swap
        )
        with self.assertRaises(RuntimeError):
            raise RuntimeError("candidate compilation failed")
        self.assertEqual(remote.read(PRODUCTION_REF), OLD_SHA)

    def test_failure_after_production_move_rolls_back_release_branch(self):
        remote = FakeRemote()
        dataform_branch_transaction.promote_production(
            OLD_SHA, CANDIDATE_SHA, remote.read, remote.compare_and_swap
        )
        self.assertEqual(remote.read(PRODUCTION_REF), CANDIDATE_SHA)
        result = dataform_branch_transaction.rollback_production(
            OLD_SHA, CANDIDATE_SHA, remote.read, remote.compare_and_swap
        )
        self.assertTrue(result["changed"])
        self.assertEqual(remote.read(PRODUCTION_REF), OLD_SHA)

    def test_concurrent_production_change_fails_closed(self):
        remote = FakeRemote()
        remote.refs[PRODUCTION_REF] = OTHER_SHA
        with self.assertRaises(dataform_branch_transaction.DataformBranchError):
            dataform_branch_transaction.promote_production(
                OLD_SHA, CANDIDATE_SHA, remote.read, remote.compare_and_swap
            )
        self.assertEqual(remote.read(PRODUCTION_REF), OTHER_SHA)

    def test_rollback_is_idempotent(self):
        remote = FakeRemote()
        result = dataform_branch_transaction.rollback_production(
            OLD_SHA, CANDIDATE_SHA, remote.read, remote.compare_and_swap
        )
        self.assertFalse(result["changed"])
        self.assertEqual(remote.operations, [])

    def test_rollback_rejects_unknown_concurrent_state(self):
        remote = FakeRemote()
        remote.refs[PRODUCTION_REF] = OTHER_SHA
        with self.assertRaises(dataform_branch_transaction.DataformBranchError):
            dataform_branch_transaction.rollback_production(
                OLD_SHA, CANDIDATE_SHA, remote.read, remote.compare_and_swap
            )


if __name__ == "__main__":
    unittest.main()
