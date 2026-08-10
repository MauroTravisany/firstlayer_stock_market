import unittest

from scripts.ci import dataform_promotion


GIT_SHA = "a" * 40
TREE_SHA = "b" * 40
SNAPSHOT_SHA = "c" * 40
PREVIOUS_SHA = "d" * 40
CANDIDATE_REF = "refs/heads/dataform-candidate-abcdef123456"
COMPILATION = "projects/p/locations/us-east1/repositories/r/compilationResults/123"


def compilation(errors=None, resolved=SNAPSHOT_SHA):
    return {
        "name": COMPILATION,
        "gitCommitish": CANDIDATE_REF.removeprefix("refs/heads/"),
        "resolvedGitCommitSha": resolved,
        "compilationErrors": errors or [],
    }


def release(result=COMPILATION):
    return {
        "name": "projects/p/locations/us-east1/repositories/r/releaseConfigs/production",
        "gitCommitish": "dataform-production",
        "releaseCompilationResult": result,
    }


class DataformPromotionTests(unittest.TestCase):
    def test_exact_compilation_and_release_transition_are_auditable(self):
        previous = release("projects/p/locations/us-east1/repositories/r/compilationResults/old")
        evidence = dataform_promotion.build_evidence(
            git_sha=GIT_SHA,
            tree_sha=TREE_SHA,
            snapshot_commit_sha=SNAPSHOT_SHA,
            candidate_ref=CANDIDATE_REF,
            previous_production_sha=PREVIOUS_SHA,
            final_production_sha=SNAPSHOT_SHA,
            compilation=compilation(),
            previous_release=previous,
            current_release=release(),
        )
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["git_sha"], GIT_SHA)
        self.assertEqual(evidence["dataform_tree_sha"], TREE_SHA)
        self.assertEqual(evidence["compilation_id"], COMPILATION)
        self.assertEqual(
            evidence["rollback"]["release_compilation_result"],
            previous["releaseCompilationResult"],
        )

    def test_compilation_errors_fail_closed(self):
        with self.assertRaises(dataform_promotion.DataformPromotionError):
            dataform_promotion.validate_compilation(
                compilation([{"message": "broken SQLX"}]),
                SNAPSHOT_SHA,
                CANDIDATE_REF.removeprefix("refs/heads/"),
            )

    def test_compilation_of_another_sha_fails_closed(self):
        with self.assertRaises(dataform_promotion.DataformPromotionError):
            dataform_promotion.validate_compilation(
                compilation(resolved="e" * 40),
                SNAPSHOT_SHA,
                CANDIDATE_REF.removeprefix("refs/heads/"),
            )

    def test_release_pointing_to_another_compilation_fails_closed(self):
        with self.assertRaises(dataform_promotion.DataformPromotionError):
            dataform_promotion.validate_release(release("other"), COMPILATION)

    def test_missing_rollback_metadata_fails_closed(self):
        with self.assertRaises(dataform_promotion.DataformPromotionError):
            dataform_promotion.build_evidence(
                git_sha=GIT_SHA,
                tree_sha=TREE_SHA,
                snapshot_commit_sha=SNAPSHOT_SHA,
                candidate_ref=CANDIDATE_REF,
                previous_production_sha=PREVIOUS_SHA,
                final_production_sha=SNAPSHOT_SHA,
                compilation=compilation(),
                previous_release={"name": release()["name"]},
                current_release=release(),
            )


if __name__ == "__main__":
    unittest.main()
