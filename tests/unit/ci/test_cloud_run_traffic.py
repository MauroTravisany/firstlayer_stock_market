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
        changed = cloud_run_traffic.restore_snapshot(
            snapshot, document, lambda command: commands.append(command)
        )
        self.assertFalse(changed)
        self.assertEqual(commands, [])

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

        def runner(command):
            calls.append(command[4])
            if command[4] == "two":
                raise RuntimeError("rollback failed")

        with self.assertRaises(cloud_run_traffic.TrafficRestoreError):
            cloud_run_traffic.restore_many(snapshots, current, runner, "project", "us-east1")
        self.assertEqual(calls[0], "three")
        self.assertIn("one", calls)


if __name__ == "__main__":
    unittest.main()
