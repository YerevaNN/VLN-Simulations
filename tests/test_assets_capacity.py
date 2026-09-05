import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "simulation"))
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_assets import sync_locked_assets
from report_capacity import capacity_report


class AssetTests(unittest.TestCase):
    def fixture(self, temp):
        root = Path(temp) / "assets"
        root.mkdir()
        original = Path(temp) / "original"
        original.write_bytes(b"pinned source")
        lock = Path(temp) / "lock.json"
        lock.write_text(json.dumps({"schema_version": "uav-assets-lock-v1", "files": [
            {"path": "models/test/file", "bytes": 13, "sha256": hashlib.sha256(b"pinned source").hexdigest(), "source_url": original.as_uri()}
        ], "source_manifest": {"assets": []}}))
        return root, original, lock

    def test_download_verify_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, original, lock = self.fixture(tmp)
            sync_locked_assets(root, lock)
            with patch("urllib.request.urlopen", side_effect=AssertionError("verification must be offline")):
                self.assertEqual(sync_locked_assets(root, lock, True)["verified_files"], 1)
            (root / "models/test/file").write_bytes(b"broken")
            with self.assertRaisesRegex(ValueError, "altered"):
                sync_locked_assets(root, lock, True)
            original.write_bytes(b"upstream changed")
            with self.assertRaisesRegex(ValueError, "differ"):
                sync_locked_assets(root, lock)
            self.assertEqual((root / "models/test/file").read_bytes(), b"broken")
            self.assertFalse(list(root.rglob(".asset-*")))

    def test_reject_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, lock = self.fixture(tmp)
            data = json.loads(lock.read_text()); data["files"][0]["path"] = "../escape"
            lock.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "escapes"):
                sync_locked_assets(root, lock)


class CapacityTests(unittest.TestCase):
    def make_attempt(self, root, attempt_id, record, duration=None):
        attempt = root / '.attempts/episode-000' / attempt_id
        attempt.mkdir(parents=True)
        (attempt / 'attempt.json').write_text(json.dumps(record))
        if duration is not None:
            private = attempt / 'episode-000'; private.mkdir()
            (private / 'manifest.json').write_text(json.dumps({'duration_s': duration}))
        return attempt

    def publish(self, root):
        p = root / 'episode-000'; p.mkdir()
        manifest = p / 'manifest.json'
        manifest.write_text(json.dumps({'duration_s': 3600, 'status': 'success', 'config_hash': 'cfg', 'wall_time_s': 1200}))
        (p / 'publication.json').write_text(json.dumps({'validation_passed': True, 'config_hash': 'cfg',
            'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}))

    def test_attempt_cost_counts_retry_once_and_keeps_cpu_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.publish(root)
            self.make_attempt(root, 'failed', {'allocated_gpu_wall_s': 1800, 'validation_wall_s': 0,
                'ended_at_unix': 10, 'validated': False, 'config_hash': 'cfg', 'output_bytes': 50}, 900)
            self.make_attempt(root, 'success', {'allocated_gpu_wall_s': 3600, 'validation_wall_s': 360,
                'ended_at_unix': 20, 'validated': True, 'config_hash': 'cfg', 'output_bytes': 100})
            (root / 'batch-one.json').write_text(json.dumps({'preparation_wall_s': 180}))
            report = capacity_report(root, 100, .5)
            observed = report['observed_attempt_allocations']
            self.assertEqual(report['primary_measurement'], 'observed_attempt_allocations')
            self.assertEqual(observed['recorded_raw_flight_hours'], 1.25)
            self.assertEqual(observed['accepted_published_flight_hours'], 1)
            self.assertEqual(observed['allocated_gpu_hours_per_accepted_hour'], 1.5)
            self.assertEqual(observed['projected_allocated_gpu_hours_at_observed_yield'], 150)
            self.assertEqual(observed['recorded_cpu_validation_hours'], .1)
            self.assertEqual(observed['recorded_preparation_wall_hours'], .05)
            self.assertEqual(observed['recorded_attempt_output_bytes'], 150)
            self.assertTrue(observed['gpu_timing_complete'])

    def test_incomplete_timing_never_becomes_complete_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.publish(root)
            self.make_attempt(root, 'success', {'allocated_gpu_wall_s': 3600, 'validation_wall_s': 0,
                'ended_at_unix': 20, 'validated': True, 'config_hash': 'cfg'})
            self.make_attempt(root, 'crashed', {'started_at_unix': 25, 'config_hash': 'cfg'})
            observed = capacity_report(root)['observed_attempt_allocations']
            self.assertFalse(observed['gpu_timing_complete'])
            self.assertIsNone(observed['allocated_gpu_hours_per_accepted_hour'])
            self.assertIsNone(observed['projected_allocated_gpu_hours_at_observed_yield'])
            self.assertEqual(observed['recorded_gpu_hours_per_accepted_hour_lower_bound'], 1)
            self.assertTrue(any('possibly interrupted' in s for s in observed['warnings']))

    def test_no_accepted_episodes_reports_attempts_without_dividing_by_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_attempt(root, 'failed', {'allocated_gpu_wall_s': 1800, 'validation_wall_s': 0,
                'ended_at_unix': 10, 'validated': False}, 900)
            observed = capacity_report(root)['observed_attempt_allocations']
            self.assertEqual(observed['accepted_published_flight_hours'], 0)
            self.assertEqual(observed['recorded_raw_flight_hours'], .25)
            self.assertIsNone(observed['allocated_gpu_hours_per_accepted_hour'])

    def test_acceptance_and_storage_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "episode-000"; p.mkdir()
            (p / "manifest.json").write_text(json.dumps({"duration_s": 3600, "wall_time_s": 1800, "files": {"x": {"bytes": 1000000000}}}))
            report = capacity_report(tmp, 100, .5, .1)
            scenario = report["scenario"]
            self.assertEqual(scenario["raw_hours_required"], 200)
            self.assertAlmostEqual(scenario["partial_timer_projected_hours_with_assumed_overhead"], 110)
            self.assertAlmostEqual(scenario["retained_dataset_TB_at_current_format"], .1)
            with self.assertRaises(ValueError): capacity_report(tmp, 100, 0)


if __name__ == "__main__":
    unittest.main()
