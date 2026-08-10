import unittest

from scripts.ci import cloud_run_traffic


def service_document(traffic, latest_ready="rev-new", latest_created="rev-new"):
    return {
        "metadata": {"name": "service"},
        "spec": {"traffic": traffic},
        "status": {
            "traffic": traffic,
            "latestReadyRevisionName": latest_ready,
            "latestCreatedRevisionName": latest_created,
        },
    }


class CloudRunTrafficTests(unittest.TestCase):
    def test_restore_plan_preserves_latest_revision_from_spec(self):
        spec = [
            {"latestRevision": True, "percent": 90, "tag": "stable"},
            {"revisionName": "rev-old", "percent": 10, "tag": "canary"},
        ]
        status = [
            {"revisionName": "rev-latest", "percent": 90, "tag": "stable"},
            {"revisionName": "rev-old", "percent": 10, "tag": "canary"},
        ]
        document = service_document(status)
        document["spec"]["traffic"] = spec
        snapshot = cloud_run_traffic.capture_snapshot("service", document)
        rendered = [
            " ".join(row)
            for row in cloud_run_traffic.build_restore_plan(
                snapshot, "project", "us-east1"
            )
        ]
        self.assertTrue(any("LATEST=90,rev-old=10" in row for row in rendered))
        self.assertTrue(any("stable=LATEST,canary=rev-old" in row for row in rendered))

    def test_snapshot_preserves_full_100_0_traffic(self):
        traffic = [
            {"revisionName": "rev-a", "percent": 100},
            {"revisionName": "rev-b", "percent": 0, "tag": "candidate"},
        ]
        snapshot = cloud_run_traffic.capture_snapshot("service", service_document(traffic))
        self.assertEqual(snapshot["spec_traffic"], traffic)
        self.assertEqual(snapshot["status_traffic"], traffic)
        self.assertEqual(snapshot["revisions"], ["rev-a", "rev-b"])
        self.assertEqual(snapshot["percentages"], {"rev-a": 100, "rev-b": 0})
        self.assertEqual(snapshot["tags"], {"candidate": "rev-b"})

    def test_restore_plan_preserves_90_10_split_and_multiple_tags(self):
        traffic = [
            {"revisionName": "rev-a", "percent": 90, "tag": "stable"},
            {"revisionName": "rev-b", "percent": 10, "tag": "canary"},
            {"revisionName": "rev-a", "percent": 0, "tag": "public"},
        ]
        snapshot = cloud_run_traffic.capture_snapshot("service", service_document(traffic))
        plan = cloud_run_traffic.build_restore_plan(snapshot, "project", "us-east1")
        rendered = [" ".join(command) for command in plan]
        self.assertTrue(any("rev-a=90,rev-b=10" in command for command in rendered))
        self.assertTrue(any("stable=rev-a,canary=rev-b,public=rev-a" in command for command in rendered))

    def test_active_revision_is_not_replaced_by_latest_ready(self):
        traffic = [{"revisionName": "rev-active", "percent": 100}]
        snapshot = cloud_run_traffic.capture_snapshot(
            "service", service_document(traffic, latest_ready="rev-unused")
        )
        plan = cloud_run_traffic.build_restore_plan(snapshot, "project", "us-east1")
        self.assertIn("rev-active=100", " ".join(plan[1]))
        self.assertNotIn("rev-unused=100", " ".join(plan[1]))

    def test_restore_is_idempotent_when_traffic_already_matches(self):
        traffic = [{"revisionName": "rev-a", "percent": 100, "tag": "stable"}]
        document = service_document(traffic)
        snapshot = cloud_run_traffic.capture_snapshot("service", document)
        commands = []
        result = cloud_run_traffic.restore_snapshot(
            snapshot,
            document,
            lambda command: commands.append(command),
            lambda: document,
        )
        self.assertFalse(result["changed"])
        self.assertTrue(result["verified"])
        self.assertEqual(commands, [])

    def test_successful_commands_but_wrong_remote_state_fail_verification(self):
        expected = service_document([{"revisionName": "rev-old", "percent": 100}])
        current = service_document([{"revisionName": "rev-new", "percent": 100}])
        snapshot = cloud_run_traffic.capture_snapshot("service", expected)
        with self.assertRaises(cloud_run_traffic.TrafficRestoreError):
            cloud_run_traffic.restore_snapshot(
                snapshot, current, lambda command: None, lambda: current
            )

    def test_partial_restoration_fails(self):
        expected = service_document(
            [
                {"revisionName": "rev-a", "percent": 90, "tag": "stable"},
                {"revisionName": "rev-b", "percent": 10, "tag": "canary"},
            ]
        )
        partial = service_document(
            [
                {"revisionName": "rev-a", "percent": 100, "tag": "stable"},
                {"revisionName": "rev-b", "percent": 0, "tag": "canary"},
            ]
        )
        snapshot = cloud_run_traffic.capture_snapshot("service", expected)
        with self.assertRaises(cloud_run_traffic.TrafficRestoreError):
            cloud_run_traffic.restore_snapshot(
                snapshot, partial, lambda command: None, lambda: partial
            )

    def test_post_restore_describe_failure_fails(self):
        expected = service_document([{"revisionName": "rev-old", "percent": 100}])
        current = service_document([{"revisionName": "rev-new", "percent": 100}])
        snapshot = cloud_run_traffic.capture_snapshot("service", expected)

        def failed_describe():
            raise cloud_run_traffic.TrafficRestoreError("describe failed")

        with self.assertRaises(cloud_run_traffic.TrafficRestoreError):
            cloud_run_traffic.restore_snapshot(
                snapshot, current, lambda command: None, failed_describe
            )

    def test_multiple_services_restore_in_reverse_and_report_failures(self):
        snapshots = [
            cloud_run_traffic.capture_snapshot(
                name, service_document([{"revisionName": f"{name}-old", "percent": 100}])
            )
            for name in ("one", "two", "three")
        ]
        current = {
            row["service"]: service_document(
                [{"revisionName": f"{row['service']}-new", "percent": 100}]
            )
            for row in snapshots
        }
        calls = []
        evidence = []

        def runner(command):
            calls.append(command[4])
            if command[4] == "two":
                raise RuntimeError("rollback failed")

        with self.assertRaises(cloud_run_traffic.TrafficRestoreError):
            cloud_run_traffic.restore_many(
                snapshots,
                current,
                runner,
                lambda service: current[service],
                "project",
                "us-east1",
                recorder=evidence.append,
            )
        self.assertEqual(calls[0], "three")
        self.assertIn("one", calls)
        self.assertEqual({row["service"] for row in evidence}, {"one", "two", "three"})
        failed = next(row for row in evidence if row["service"] == "two")
        self.assertFalse(failed["verified"])


if __name__ == "__main__":
    unittest.main()
